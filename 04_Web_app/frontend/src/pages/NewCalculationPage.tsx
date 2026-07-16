import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type RefObject,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type {
  CampaignPreview,
  CampaignUpload,
  ValidationIssue,
  ValidationResult,
} from "../entities/lifecycle/types";
import {
  NEW_CALCULATION_FILE_ACCEPT,
  NEW_CALCULATION_SCENARIOS,
  SCENARIO_RECOMMENDATION_RULES,
  buildScenarioInvariantSnapshot,
  checkCampaignFilePolicy,
  getValidationTopStatus,
  groupIssueAffectedEntities,
  guardSingleCampaign,
  resolveNewCalculationStep,
  uploadCanProceedToValidation,
  type NewCalculationStep,
} from "../features/new-calculation/newCalculationFlow";
import {
  CalculationProfileRequestError,
  CalculationProfileUnavailableError,
  UnsupportedCalculationProfileError,
  campaignPlanTemplateUrl,
  getCalculationProfile,
  type CalculationProfile,
} from "../shared/api/new-calculation-client";
import {
  createIdempotencyKey,
  createJob,
  getUpload,
  getValidation,
  pollUntil,
  requestValidation,
  uploadCampaign,
} from "../shared/api/lifecycle-client";
import { CampaignPreviewVisuals, ValidationChecks } from "../features/new-calculation/NewCalculationPreview";
import { formatDate, formatInteger, formatRub } from "../shared/formatters/metrics";
import { Button } from "../shared/ui/Button";
import { StatusBadge } from "../shared/ui/StatusBadge";
import styles from "./new-calculation.module.css";

type RemoteActivity =
  | "idle"
  | "uploading"
  | "loading-upload"
  | "starting-validation"
  | "loading-validation"
  | "creating-job";
type ValidationTone = "ready" | "warning" | "blocked";

interface RemoteActivityState {
  code: RemoteActivity;
  location: string | null;
}

interface FlowErrorState {
  context: string;
  kind: "load" | "action";
  message: string;
}

type CalculationProfileState =
  | { validationId: string; status: "ready"; profile: CalculationProfile }
  | { validationId: string; status: "unavailable" | "unsupported" | "error" };

type CalculationProfileViewState = CalculationProfileState
  | { validationId: string; status: "loading" };

const forbiddenUserText = /\b(api|backend|validation preview|support|candidate_id|attempt_id|posterior)\b/i;

const stepLabels = ["Загрузка", "Проверка", "Сценарии", "Расчет"];

function getCurrentStep(step: NewCalculationStep, activity: RemoteActivity): number {
  if (activity === "creating-job") return 4;
  if (step === "review") return 2;
  if (step === "scenarios") return 3;
  return 1;
}

function getFileError(file: File): string | null {
  const policy = checkCampaignFilePolicy(file.name);
  return policy.accepted ? null : policy.message;
}

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} Б`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1).replace(".0", "")} КБ`;
  return `${(size / (1024 * 1024)).toFixed(1).replace(".0", "")} МБ`;
}

function safeError(caught: unknown, fallback: string): string {
  if (!(caught instanceof Error)) return fallback;
  return safeMarketerText(caught.message, fallback);
}

function safeMarketerText(value: string, fallback: string): string {
  const message = value.trim();
  if (!message || forbiddenUserText.test(message)) return fallback;
  return message;
}

function optionalSafeMarketerText(value: string | undefined): string | null {
  if (!value) return null;
  const message = value.trim();
  if (!message || forbiddenUserText.test(message)) return null;
  return message;
}

function isAbortError(caught: unknown): boolean {
  return typeof caught === "object" && caught !== null && "name" in caught
    && caught.name === "AbortError";
}

function flowContext(
  step: NewCalculationStep,
  uploadId: string | null,
  validationId: string | null,
): string {
  if (step === "upload-result") return `${step}:${uploadId ?? "missing"}`;
  if (step === "review" || step === "scenarios") {
    return `${step}:${validationId ?? "missing"}`;
  }
  return "upload:new";
}

function browserLocationKey(): string {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function getValidationTone(validation: ValidationResult): ValidationTone {
  const status = getValidationTopStatus(validation);
  if (status.code === "ready") return "ready";
  if (status.code === "warning") return "warning";
  return "blocked";
}

function sourceFileName(upload: CampaignUpload | null): string {
  return upload?.original_file.display_name ?? "Нет данных";
}

function Stepper({ current }: { current: number }) {
  return (
    <ol className={styles.stepper} aria-label="Этапы нового расчета">
      {stepLabels.map((label, index) => {
        const position = index + 1;
        const state = position < current ? "done" : position === current ? "active" : "future";
        return (
          <li
            key={label}
            className={styles[`step_${state}`]}
            aria-current={state === "active" ? "step" : undefined}
          >
            <span className={styles.stepNumber}>{position}</span>
            <span className={styles.stepLabel}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function PageHero({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return (
    <header className={styles.hero}>
      <div className={styles.heroCopy}>
        <span className={styles.eyebrow}>{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className={styles.rulePill}>Один файл = одна кампания</div>
    </header>
  );
}

function UploadGlyph() {
  return (
    <svg className={styles.uploadGlyph} viewBox="0 0 48 48" aria-hidden="true">
      <path d="M24 31V8m0 0-8 8m8-8 8 8" />
      <path d="M10 28v8a4 4 0 0 0 4 4h20a4 4 0 0 0 4-4v-8" />
    </svg>
  );
}

function LoadingPanel({ message }: { message: string }) {
  return (
    <section className={styles.loadingPanel} aria-live="polite" aria-busy="true">
      <span className={styles.loadingMark} aria-hidden="true" />
      <div>
        <span className={styles.eyebrow}>Подождите</span>
        <h2>{message}</h2>
        <p>Страница обновится автоматически.</p>
      </div>
    </section>
  );
}

function AffectedContext({ issue, campaigns }: { issue: ValidationIssue; campaigns: CampaignPreview[] }) {
  const groups = groupIssueAffectedEntities(issue, campaigns);
  const values = [
    ...groups.campaigns.map((value) => `Кампания: ${value}`),
    ...groups.segments.map((value) => `Сегмент: ${value}`),
    ...groups.geographies.map((value) => `Гео: ${value}`),
    ...groups.channels.map((value) => `Канал: ${value}`),
    ...groups.geoChannelPairs.map((value) => `Связка гео × канал: ${value}`),
    ...groups.targets.map((value) => `Показатель: ${value}`),
  ];

  if (values.length === 0) {
    return <span className={styles.contextChip}>Кампания целиком</span>;
  }
  return (
    <>
      {values.map((value) => (
        <span className={styles.contextChip} key={value}>{value}</span>
      ))}
    </>
  );
}

interface UploadStepProps {
  file: File | null;
  fileError: string | null;
  dragging: boolean;
  busy: boolean;
  inputRef: RefObject<HTMLInputElement | null>;
  onInputChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onDrop: (event: DragEvent<HTMLLabelElement>) => void;
  onDragEnter: (event: DragEvent<HTMLLabelElement>) => void;
  onDragLeave: (event: DragEvent<HTMLLabelElement>) => void;
  onChoose: () => void;
  onRemove: () => void;
  onUpload: () => void;
}

function UploadStep({
  file,
  fileError,
  dragging,
  busy,
  inputRef,
  onInputChange,
  onDrop,
  onDragEnter,
  onDragLeave,
  onChoose,
  onRemove,
  onUpload,
}: UploadStepProps) {
  return (
    <div className={styles.uploadLayout}>
      <section className={styles.uploadCard} aria-labelledby="upload-title">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Шаг 1 из 4</span>
            <h2 id="upload-title">Загрузите медиаплан</h2>
          </div>
          <span className={styles.formatLabel}>XLSX или CSV</span>
        </div>

        <label
          className={`${styles.dropzone} ${dragging ? styles.dropzoneActive : ""} ${file ? styles.dropzoneSelected : ""}`}
          onDragEnter={onDragEnter}
          onDragOver={onDragEnter}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
        >
          <input
            ref={inputRef}
            className={styles.dropzoneInput}
            type="file"
            accept={NEW_CALCULATION_FILE_ACCEPT}
            onChange={onInputChange}
            aria-label="Файл медиаплана"
            disabled={busy}
          />
          <UploadGlyph />
          {file ? (
            <div className={styles.selectedFile}>
              <span className={styles.selectedLabel}>Файл выбран</span>
              <strong>{file.name}</strong>
              <span>{formatFileSize(file.size)}</span>
            </div>
          ) : (
            <div>
              <strong>Перетащите файл сюда</strong>
              <span>или нажмите, чтобы выбрать на компьютере</span>
            </div>
          )}
        </label>

        {fileError ? <p className={styles.inlineError} role="alert">{fileError}</p> : null}

        <div className={styles.uploadActions}>
          <div className={styles.secondaryActions}>
            <Button type="button" onClick={onChoose} disabled={busy}>
              {file ? "Заменить файл" : "Выбрать файл"}
            </Button>
            {file ? <Button type="button" onClick={onRemove} disabled={busy}>Удалить</Button> : null}
          </div>
          <Button variant="primary" type="button" onClick={onUpload} disabled={!file || Boolean(fileError) || busy}>
            {busy ? "Загружаем файл…" : "Загрузить файл"}
          </Button>
        </div>
      </section>

      <aside className={styles.requirements} aria-labelledby="requirements-title">
        <span className={styles.eyebrow}>Перед загрузкой</span>
        <h2 id="requirements-title">Проверьте файл</h2>
        <ul>
          <li>Одна кампания</li>
          <li>Указан сегмент</li>
          <li>Указаны гео и канал</li>
          <li>Бюджет в рублях</li>
          <li>Даты указаны</li>
          <li>Нет объединенных ячеек</li>
        </ul>
        <div className={styles.templateBlock}>
          <a
            href={campaignPlanTemplateUrl()}
            download="campaign-plan-template.xlsx"
          >
            Скачать шаблон медиаплана
          </a>
          <p>В шаблоне есть форматы по дням и по периоду с примером заполнения</p>
        </div>
      </aside>
    </div>
  );
}

function UploadResultStep({
  upload,
  onContinue,
  onReset,
  busy,
}: {
  upload: CampaignUpload;
  onContinue: () => void;
  onReset: () => void;
  busy: boolean;
}) {
  const campaignGuard = guardSingleCampaign(upload.detected_campaigns_n);
  const exactlyOne = campaignGuard.allowed;
  return (
    <section className={`${styles.resultCard} ${!exactlyOne ? styles.resultCardBlocked : ""}`}>
      <div className={styles.resultLead}>
        <span className={styles.resultIcon} aria-hidden="true">{exactlyOne ? "✓" : "!"}</span>
        <div>
          <span className={styles.eyebrow}>Файл обработан</span>
          <h2>{exactlyOne ? "Файл успешно прочитан" : campaignGuard.title}</h2>
          <p>
            {exactlyOne
              ? "Проверьте сводку и переходите к проверке кампании."
              : campaignGuard.description}
          </p>
        </div>
      </div>
      <dl className={styles.fileSummary}>
        <div><dt>Файл</dt><dd>{upload.original_file.display_name}</dd></div>
        <div><dt>Размер</dt><dd>{formatFileSize(upload.original_file.size_bytes)}</dd></div>
        <div><dt>Строк</dt><dd>{upload.source_rows_n ?? "Нет данных"}</dd></div>
        <div><dt>Кампаний</dt><dd>{upload.detected_campaigns_n ?? "Нет данных"}</dd></div>
      </dl>
      <div className={styles.footerActions}>
        <Button type="button" onClick={onReset} disabled={busy}>Загрузить другой файл</Button>
        {exactlyOne ? (
          <Button variant="primary" type="button" onClick={onContinue} disabled={busy}>
            {busy ? "Начинаем проверку…" : "Продолжить к проверке"}
          </Button>
        ) : null}
      </div>
    </section>
  );
}

function CampaignSummary({ campaign, upload }: { campaign: CampaignPreview; upload: CampaignUpload | null }) {
  return (
    <section className={styles.campaignSummary} aria-labelledby="campaign-summary-title">
      <div className={styles.summaryHeading}>
        <div>
          <span className={styles.eyebrow}>Кампания</span>
          <h2 id="campaign-summary-title">{campaign.campaign_name}</h2>
        </div>
        <strong className={styles.summaryBudget}>{formatRub(campaign.uploaded_budget_rub)}</strong>
      </div>
      <dl className={styles.summaryGrid}>
        <div><dt>Сегмент</dt><dd>{campaign.segments.join(", ") || "Нет данных"}</dd></div>
        <div><dt>Период</dt><dd>{formatDate(campaign.start_date)} — {formatDate(campaign.end_date)}</dd></div>
        <div><dt>Активных дней</dt><dd>{campaign.active_days}</dd></div>
        <div><dt>Каналы</dt><dd>{campaign.channels.join(", ") || "Нет данных"}</dd></div>
        <div><dt>Географии</dt><dd>{campaign.geographies.join(", ") || "Нет данных"}</dd></div>
        <div><dt>Строк в файле</dt><dd>{campaign.source_rows_n}</dd></div>
        <div className={styles.summaryWide}><dt>Исходный файл</dt><dd>{sourceFileName(upload)}</dd></div>
      </dl>
    </section>
  );
}

function ValidationIssues({ validation }: { validation: ValidationResult }) {
  const issues = [...validation.blocking_errors, ...validation.warnings];
  if (issues.length === 0) {
    return (
      <section className={styles.noIssues} aria-label="Замечания">
        <span aria-hidden="true">✓</span>
        <div><h2>Замечаний не получено</h2><p>По текущему результату можно перейти к сценариям.</p></div>
      </section>
    );
  }
  return (
    <section className={styles.issuesSection} aria-labelledby="issues-title">
      <div className={styles.sectionHeading}>
        <div><span className={styles.eyebrow}>Результат проверки</span><h2 id="issues-title">Замечания к кампании</h2></div>
        <span className={styles.issueCount}>{issues.length}</span>
      </div>
      <div className={styles.issueGrid}>
        {issues.map((issue, index) => {
          const what = optionalSafeMarketerText(issue.what)
            ?? safeMarketerText(issue.display_text, "Получено замечание к кампании.");
          const why = optionalSafeMarketerText(issue.why);
          const recommendedAction = optionalSafeMarketerText(issue.recommended_action);
          return (
            <article className={styles.issueCard} key={`${issue.code}-${index}`}>
            <div className={styles.issueTopline}>
              <StatusBadge tone={issue.severity === "blocking" ? "danger" : "warning"}>
                {issue.severity === "blocking" ? "Нужно исправить" : "Замечание"}
              </StatusBadge>
              <span>{issue.severity === "blocking" ? "Блокирует расчет" : "Не блокирует расчет"}</span>
            </div>
            <h3>Что обнаружено</h3>
            <p className={styles.issueText}>{what}</p>
            <div className={styles.contextList}><AffectedContext issue={issue} campaigns={validation.campaigns} /></div>
            {why || recommendedAction ? (
              <dl className={styles.issueDetails}>
                {why ? <div><dt>Почему это важно</dt><dd>{why}</dd></div> : null}
                {recommendedAction ? <div><dt>Что можно сделать</dt><dd>{recommendedAction}</dd></div> : null}
              </dl>
            ) : null}
          </article>
          );
        })}
      </div>
    </section>
  );
}

function ValidationStep({
  validation,
  upload,
  onReset,
  onScenarios,
}: {
  validation: ValidationResult;
  upload: CampaignUpload | null;
  onReset: () => void;
  onScenarios: () => void;
}) {
  const tone = getValidationTone(validation);
  const topStatus = getValidationTopStatus(validation);
  const campaign = validation.campaigns.length === 1 ? validation.campaigns[0] : null;
  return (
    <div className={styles.validationPage}>
      <section className={`${styles.validationStatus} ${styles[`validationStatus_${tone}`]}`}>
        <div>
          <div className={styles.statusMeta}>
            <span className={styles.eyebrow}>Шаг 2 из 4</span>
            {validation.record_origin === "synthetic_fixture" ? (
              <StatusBadge tone="warning">Демонстрационные данные</StatusBadge>
            ) : null}
          </div>
          <h2>{topStatus.label}</h2>
          <p>{topStatus.description}</p>
        </div>
        <span className={styles.statusSymbol} aria-hidden="true">{tone === "ready" ? "✓" : "!"}</span>
      </section>

      {campaign ? <CampaignSummary campaign={campaign} upload={upload} /> : (
        <section className={styles.blockedNotice} role="alert">
          <h2>Нельзя продолжить с этим файлом</h2>
          <p>В результате проверки должна быть ровно одна кампания.</p>
        </section>
      )}

      <ValidationChecks checks={validation.preview?.checks} />
      <ValidationIssues validation={validation} />

      <section className={styles.s5Explanation}>
        <span className={styles.shieldMark} aria-hidden="true">S5</span>
        <div>
          <h2>Как будет проверяться устойчивость</h2>
          <p>Сценарий 5 попробует перераспределить бюджет между исходными каналами и гео так, чтобы план оставался в более надежной исторической зоне. Новые каналы и гео добавляться не будут.</p>
        </div>
      </section>

      <CampaignPreviewVisuals preview={validation.preview} />

      <div className={styles.footerActions}>
        <Button type="button" onClick={onReset}>{tone === "blocked" ? "Загрузить исправленный файл" : "Загрузить другой файл"}</Button>
        {tone !== "blocked" ? (
          <Button variant="primary" type="button" onClick={onScenarios}>
            {tone === "warning" ? "Продолжить с замечаниями" : "Продолжить к сценариям"}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function ScenariosStep({
  validation,
  calculationProfile,
  onBack,
  onStart,
  busy,
}: {
  validation: ValidationResult;
  calculationProfile: CalculationProfileViewState;
  onBack: () => void;
  onStart: () => void;
  busy: boolean;
}) {
  const campaign = validation.campaigns[0];
  const invariant = buildScenarioInvariantSnapshot(campaign);
  return (
    <div className={styles.scenariosPage}>
      <section className={styles.scenarioIntro}>
        <div>
          <div className={styles.statusMeta}>
            <span className={styles.eyebrow}>Шаг 3 из 4</span>
            {validation.record_origin === "synthetic_fixture" ? (
              <StatusBadge tone="warning">Демонстрационные данные</StatusBadge>
            ) : null}
          </div>
          <h2>Шесть сценариев будут рассчитаны автоматически</h2>
        </div>
        <p>Выбирать сценарии или настраивать поиск не нужно. До запуска здесь нет прогнозных значений.</p>
      </section>

      <section className={styles.scenarioGrid} aria-label="Сценарии расчета">
        {NEW_CALCULATION_SCENARIOS.map((scenario, index) => (
          <article className={`${styles.scenarioCard} ${styles[`scenario_${scenario.role}`]}`} key={scenario.id}>
            <div className={styles.scenarioMeta}>
              <strong>S{index + 1}</strong>
              <span>{scenario.badge}</span>
            </div>
            <h3>{scenario.title}</h3>
            <p>{scenario.description}</p>
            {scenario.id === "S05" ? <div className={styles.scenarioPrinciple}>S5 — сначала устойчивость</div> : null}
            {scenario.id === "S06" ? (
              <div className={styles.scenarioProfile} aria-live="polite">
                <span>S6 — поиск эффективности с обязательной проверкой устойчивости</span>
                {calculationProfile.status === "ready" ? (
                  <>
                    <strong>
                      {formatInteger(calculationProfile.profile.scenario6_attempt_budget)} вариантов
                    </strong>
                    <small>
                      {calculationProfile.profile.profile_label} · {calculationProfile.profile.model_version_label}
                    </small>
                  </>
                ) : (
                  <strong>
                    {calculationProfile.status === "loading"
                      ? "Загружаем число вариантов…"
                      : "Число вариантов пока недоступно"}
                  </strong>
                )}
              </div>
            ) : null}
          </article>
        ))}
      </section>

      <section className={styles.invariants} aria-labelledby="invariants-title">
        <div><span className={styles.eyebrow}>Неизменные границы</span><h2 id="invariants-title">Что останется прежним</h2></div>
        <dl>
          <div><dt>Общий бюджет</dt><dd>{formatRub(invariant.totalBudgetRub)}</dd></div>
          <div><dt>Даты</dt><dd>{formatDate(invariant.startDate)} — {formatDate(invariant.endDate)}</dd></div>
          <div><dt>Исходные каналы</dt><dd>{invariant.channels.join(", ")}</dd></div>
          <div><dt>Исходные гео</dt><dd>{invariant.geographies.join(", ")}</dd></div>
          <div><dt>Исходные связки гео × канал</dt><dd>{invariant.existingCellsRule} Количество не предоставлено.</dd></div>
        </dl>
      </section>

      <section className={styles.recommendationLogic} aria-labelledby="logic-title">
        <div><span className={styles.eyebrow}>После расчета</span><h2 id="logic-title">Как появится рекомендация</h2></div>
        <ol>{SCENARIO_RECOMMENDATION_RULES.map((rule) => <li key={rule}>{rule}</li>)}</ol>
        <p>Рекомендация относится к распределению бюджета, а не к решению запускать кампанию.</p>
      </section>

      <div className={styles.footerActions}>
        <Button type="button" onClick={onBack} disabled={busy}>Назад к проверке</Button>
        <Button variant="primary" type="button" onClick={onStart} disabled={busy}>
          {busy ? "Создаем расчет…" : "Запустить расчет"}
        </Button>
      </div>
    </div>
  );
}

export function NewCalculationPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const inputRef = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(false);
  const uploadActionRef = useRef<{ file: File; idempotencyKey: string } | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [upload, setUpload] = useState<CampaignUpload | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [activityState, setActivityState] = useState<RemoteActivityState>({
    code: "idle",
    location: null,
  });
  const [errorState, setErrorState] = useState<FlowErrorState | null>(null);
  const [calculationProfileState, setCalculationProfileState] = useState<CalculationProfileState | null>(null);

  const routeState = useMemo(() => resolveNewCalculationStep(searchParams), [searchParams]);
  const flowStep = routeState.step;
  const uploadId = routeState.uploadId;
  const validationId = routeState.validationId;
  const currentContext = flowContext(flowStep, uploadId, validationId);
  const error = errorState?.context === currentContext ? errorState.message : null;
  const hasLoadError = errorState?.context === currentContext && errorState.kind === "load";
  const routeUpload = uploadId && upload?.upload_id === uploadId ? upload : null;
  const routeValidation = validationId && validation?.validation_id === validationId
    ? validation
    : null;
  const validationSourceUpload = routeValidation && upload?.upload_id === routeValidation.upload_id
    ? upload
    : null;
  const activity = activityState.location && activityState.location !== browserLocationKey()
    ? "idle"
    : activityState.code;
  const currentStep = getCurrentStep(flowStep, activity);
  const activeCalculationProfile: CalculationProfileViewState =
    validationId && calculationProfileState?.validationId === validationId
      ? calculationProfileState
      : { validationId: validationId ?? "validation_pending", status: "loading" };

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const actionMayUpdateCurrentRoute = (actionLocation: string): boolean => {
    if (!mountedRef.current) return false;
    if (browserLocationKey() === actionLocation) return true;
    setActivityState((current) => current.location === actionLocation
      ? { code: "idle", location: null }
      : current);
    return false;
  };

  useEffect(() => {
    if (flowStep !== "upload-result" || !uploadId) return;
    const controller = new AbortController();
    const requestContext = flowContext("upload-result", uploadId, null);
    pollUntil(
      () => getUpload(uploadId, controller.signal),
      (record) => record.status.code !== "received",
      (record) => setUpload(record),
      { signal: controller.signal },
    )
      .then((record) => {
        if (controller.signal.aborted) return;
        if (record.status.code !== "parsed") {
          throw new Error("Не удалось прочитать файл. Проверьте формат и структуру, затем загрузите его снова.");
        }
        setErrorState((current) => current?.context === requestContext ? null : current);
        setUpload(record);
        setActivityState({ code: "idle", location: null });
      })
      .catch((caught: unknown) => {
        if (isAbortError(caught) || controller.signal.aborted) return;
        setErrorState({
          context: requestContext,
          kind: "load",
          message: safeError(caught, "Не удалось получить результат обработки файла. Попробуйте загрузить его снова."),
        });
        setActivityState({ code: "idle", location: null });
      });
    return () => controller.abort();
  }, [flowStep, uploadId]);

  useEffect(() => {
    if ((flowStep !== "review" && flowStep !== "scenarios") || !validationId) return;
    const controller = new AbortController();
    const requestContext = flowContext(flowStep, null, validationId);
    pollUntil(
      () => getValidation(validationId, controller.signal),
      (record) => record.status.code !== "running",
      (record) => setValidation(record),
      { signal: controller.signal },
    )
      .then(async (record) => {
        if (controller.signal.aborted) return;
        setErrorState((current) => current?.context === requestContext ? null : current);
        setValidation(record);
        try {
          const sourceUpload = await getUpload(record.upload_id, controller.signal);
          if (!controller.signal.aborted) setUpload(sourceUpload);
        } catch (caught) {
          if (!isAbortError(caught) && !controller.signal.aborted) setUpload(null);
        }
        if (controller.signal.aborted) return;
        if (flowStep === "scenarios" && getValidationTone(record) === "blocked") {
          navigate(`/calculations/new?validationId=${encodeURIComponent(record.validation_id)}&step=review`, { replace: true });
          return;
        }
        setActivityState({ code: "idle", location: null });
      })
      .catch((caught: unknown) => {
        if (isAbortError(caught) || controller.signal.aborted) return;
        setErrorState({
          context: requestContext,
          kind: "load",
          message: safeError(caught, "Не удалось получить результат проверки. Попробуйте открыть страницу еще раз."),
        });
        setActivityState({ code: "idle", location: null });
      });
    return () => controller.abort();
  }, [flowStep, navigate, validationId]);

  useEffect(() => {
    if (flowStep !== "scenarios" || !validationId) return;
    const controller = new AbortController();
    getCalculationProfile(controller.signal)
      .then((profile) => {
        if (controller.signal.aborted) return;
        setCalculationProfileState({ validationId, status: "ready", profile });
      })
      .catch((caught: unknown) => {
        if (isAbortError(caught) || controller.signal.aborted) return;
        const status = caught instanceof CalculationProfileUnavailableError
          ? "unavailable"
          : caught instanceof UnsupportedCalculationProfileError
            ? "unsupported"
            : caught instanceof CalculationProfileRequestError
              ? "error"
              : "error";
        setCalculationProfileState({ validationId, status });
      });
    return () => controller.abort();
  }, [flowStep, validationId]);

  const resetToUpload = (openPicker = false) => {
    setFile(null);
    uploadActionRef.current = null;
    setFileError(null);
    setUpload(null);
    setValidation(null);
    setErrorState(null);
    setActivityState({ code: "idle", location: null });
    if (inputRef.current) inputRef.current.value = "";
    navigate("/calculations/new", { replace: true });
    if (openPicker) window.setTimeout(() => inputRef.current?.click(), 0);
  };

  const acceptFile = (candidate: File | undefined) => {
    if (!candidate) return;
    const nextError = getFileError(candidate);
    uploadActionRef.current = nextError ? null : {
      file: candidate,
      idempotencyKey: createIdempotencyKey("upload"),
    };
    setErrorState(null);
    setUpload(null);
    setValidation(null);
    setFileError(nextError);
    setFile(nextError ? null : candidate);
    if (nextError && inputRef.current) inputRef.current.value = "";
    if (flowStep !== "upload") navigate("/calculations/new");
  };

  const onInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    acceptFile(event.target.files?.[0]);
  };

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    if (activity === "uploading") return;
    if (event.dataTransfer.files.length !== 1) {
      setFile(null);
      uploadActionRef.current = null;
      setFileError("Загрузите один файл. Для каждой кампании нужен отдельный медиаплан.");
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    acceptFile(event.dataTransfer.files?.[0]);
  };

  const onDragEnter = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    if (activity === "uploading") return;
    if (!event.dataTransfer.types.includes("Files")) return;
    setDragging(true);
  };

  const onDragLeave = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setDragging(false);
  };

  const beginUpload = async () => {
    if (!file || fileError) return;
    const actionContext = currentContext;
    const actionLocation = browserLocationKey();
    const uploadAction = uploadActionRef.current?.file === file
      ? uploadActionRef.current
      : { file, idempotencyKey: createIdempotencyKey("upload") };
    uploadActionRef.current = uploadAction;
    setActivityState({ code: "uploading", location: actionLocation });
    setErrorState(null);
    try {
      const accepted = await uploadCampaign(file, uploadAction.idempotencyKey);
      if (!actionMayUpdateCurrentRoute(actionLocation)) return;
      setUpload(accepted);
      navigate(`/calculations/new?uploadId=${encodeURIComponent(accepted.upload_id)}&step=upload-result`);
    } catch (caught) {
      if (!actionMayUpdateCurrentRoute(actionLocation)) return;
      setErrorState({
        context: actionContext,
        kind: "action",
        message: safeError(caught, "Не удалось загрузить файл. Проверьте соединение и попробуйте снова."),
      });
      setActivityState({ code: "idle", location: null });
    }
  };

  const beginValidation = async () => {
    if (!routeUpload || !uploadCanProceedToValidation(routeUpload)) return;
    const actionContext = currentContext;
    const actionLocation = browserLocationKey();
    setActivityState({ code: "starting-validation", location: actionLocation });
    setErrorState(null);
    try {
      const started = await requestValidation(
        routeUpload.upload_id,
        `validation:${routeUpload.upload_id}`,
      );
      if (!actionMayUpdateCurrentRoute(actionLocation)) return;
      setValidation(started);
      navigate(`/calculations/new?validationId=${encodeURIComponent(started.validation_id)}&step=review`);
    } catch (caught) {
      if (!actionMayUpdateCurrentRoute(actionLocation)) return;
      setErrorState({
        context: actionContext,
        kind: "action",
        message: safeError(caught, "Не удалось начать проверку кампании. Попробуйте еще раз."),
      });
      setActivityState({ code: "idle", location: null });
    }
  };

  const startJob = async () => {
    if (!routeValidation || getValidationTone(routeValidation) === "blocked" || flowStep !== "scenarios") return;
    const actionContext = currentContext;
    const actionLocation = browserLocationKey();
    setActivityState({ code: "creating-job", location: actionLocation });
    setErrorState(null);
    try {
      const job = await createJob(
        routeValidation.validation_id,
        `job:${routeValidation.validation_id}`,
      );
      if (!actionMayUpdateCurrentRoute(actionLocation)) return;
      navigate(`/calculations/${job.job_id}/progress`);
    } catch (caught) {
      if (!actionMayUpdateCurrentRoute(actionLocation)) return;
      setErrorState({
        context: actionContext,
        kind: "action",
        message: safeError(caught, "Не удалось запустить расчет. Попробуйте еще раз."),
      });
      setActivityState({ code: "idle", location: null });
    }
  };

  const loadingUpload = flowStep === "upload-result" && !error && (
    !routeUpload
    || routeUpload.status.code === "received"
    || activity === "uploading"
    || activity === "loading-upload"
  );
  const loadingValidation =
    (flowStep === "review" || flowStep === "scenarios") && !error && (
      !routeValidation
      || routeValidation.status.code === "running"
      || activity === "starting-validation"
      || activity === "loading-validation"
    );

  return (
    <div className={styles.page}>
      <PageHero
        eyebrow="Подготовка кампании"
        title="Новый расчет"
        description="Загрузите медиаплан одной будущей кампании. После проверки система рассчитает все шесть сценариев и предложит распределение бюджета."
      />
      <Stepper current={currentStep} />

      {error ? (
        <div className={styles.pageError} role="alert">
          <span>{error}</span>
          {flowStep !== "upload" ? (
            <Button type="button" onClick={() => resetToUpload(false)}>Загрузить другой файл</Button>
          ) : null}
        </div>
      ) : null}

      {flowStep === "upload" ? (
        <UploadStep
          file={file}
          fileError={fileError}
          dragging={dragging}
          busy={activity === "uploading"}
          inputRef={inputRef}
          onInputChange={onInputChange}
          onDrop={onDrop}
          onDragEnter={onDragEnter}
          onDragLeave={onDragLeave}
          onChoose={() => {
            if (!inputRef.current) return;
            inputRef.current.value = "";
            inputRef.current.click();
          }}
          onRemove={() => {
            setFile(null);
            uploadActionRef.current = null;
            setFileError(null);
            if (inputRef.current) inputRef.current.value = "";
          }}
          onUpload={beginUpload}
        />
      ) : null}

      {loadingUpload ? <LoadingPanel message="Читаем файл" /> : null}
      {flowStep === "upload-result" && !hasLoadError && routeUpload?.status.code === "parsed" && activity !== "loading-upload" ? (
        <UploadResultStep
          upload={routeUpload}
          onContinue={beginValidation}
          onReset={() => resetToUpload(false)}
          busy={activity === "starting-validation"}
        />
      ) : null}

      {loadingValidation ? <LoadingPanel message="Проверяем кампанию" /> : null}
      {flowStep === "review" && !hasLoadError && routeValidation && routeValidation.status.code !== "running" && activity !== "loading-validation" ? (
        <ValidationStep
          validation={routeValidation}
          upload={validationSourceUpload}
          onReset={() => resetToUpload(false)}
          onScenarios={() => navigate(`/calculations/new?validationId=${encodeURIComponent(routeValidation.validation_id)}&step=scenarios`)}
        />
      ) : null}

      {flowStep === "scenarios" && !hasLoadError && routeValidation && getValidationTone(routeValidation) !== "blocked" && activity !== "loading-validation" ? (
        <ScenariosStep
          validation={routeValidation}
          calculationProfile={activeCalculationProfile}
          onBack={() => navigate(`/calculations/new?validationId=${encodeURIComponent(routeValidation.validation_id)}&step=review`)}
          onStart={startJob}
          busy={activity === "creating-job"}
        />
      ) : null}
    </div>
  );
}
