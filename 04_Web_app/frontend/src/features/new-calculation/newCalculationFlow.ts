import type {
  CampaignPreview,
  CampaignUpload,
  ValidationIssue,
  ValidationResult,
} from "../../entities/lifecycle/types";

export const NEW_CALCULATION_FILE_ACCEPT = ".csv,.xlsx";

export type CampaignFilePolicyCode =
  | "accepted"
  | "missing-name"
  | "unsupported-format";

export interface CampaignFilePolicyResult {
  accepted: boolean;
  code: CampaignFilePolicyCode;
  extension: ".csv" | ".xlsx" | null;
  message: string;
}

const ACCEPTED_FILE_EXTENSIONS = new Set([".csv", ".xlsx"] as const);

export function checkCampaignFilePolicy(fileName: string): CampaignFilePolicyResult {
  const normalizedName = fileName.trim();
  const lastDot = normalizedName.lastIndexOf(".");

  if (!normalizedName || lastDot <= 0 || lastDot === normalizedName.length - 1) {
    return {
      accepted: false,
      code: "missing-name",
      extension: null,
      message: "Выберите файл медиаплана в формате XLSX или CSV.",
    };
  }

  const extension = normalizedName.slice(lastDot).toLowerCase();
  if (!ACCEPTED_FILE_EXTENSIONS.has(extension as ".csv" | ".xlsx")) {
    return {
      accepted: false,
      code: "unsupported-format",
      extension: null,
      message: "Поддерживаются только файлы XLSX и CSV.",
    };
  }

  return {
    accepted: true,
    code: "accepted",
    extension: extension as ".csv" | ".xlsx",
    message: "Файл готов к загрузке.",
  };
}

export type NewCalculationStep = "upload" | "upload-result" | "review" | "scenarios";

export interface NewCalculationRouteState {
  step: NewCalculationStep;
  uploadId: string | null;
  validationId: string | null;
}

const OPAQUE_ID_PATTERN = /^[a-z][a-z0-9_]*_[0-9a-f]{12,64}$/;

function queryParams(input: URLSearchParams | string): URLSearchParams {
  if (input instanceof URLSearchParams) return input;
  return new URLSearchParams(input.startsWith("?") ? input.slice(1) : input);
}

function safeResourceId(value: string | null, prefix: "upload" | "validation"): string | null {
  if (!value || !OPAQUE_ID_PATTERN.test(value) || !value.startsWith(`${prefix}_`)) return null;
  return value;
}

export function resolveNewCalculationStep(
  input: URLSearchParams | string,
): NewCalculationRouteState {
  const params = queryParams(input);
  const requestedStep = params.get("step");
  const uploadId = safeResourceId(params.get("uploadId"), "upload");
  const validationId = safeResourceId(params.get("validationId"), "validation");

  if (requestedStep === "scenarios" && validationId) {
    return { step: "scenarios", uploadId, validationId };
  }
  if ((requestedStep === "review" || requestedStep === null) && validationId) {
    return { step: "review", uploadId, validationId };
  }
  if (requestedStep === "upload-result" && uploadId) {
    return { step: "upload-result", uploadId, validationId: null };
  }
  return { step: "upload", uploadId: null, validationId: null };
}

export type SingleCampaignGuardState = "pending" | "single" | "missing" | "multiple";

export interface SingleCampaignGuard {
  allowed: boolean;
  state: SingleCampaignGuardState;
  title: string;
  description: string;
}

export function guardSingleCampaign(count: number | null | undefined): SingleCampaignGuard {
  if (count === 1) {
    return {
      allowed: true,
      state: "single",
      title: "Обнаружена одна кампания",
      description: "Файл соответствует правилу «Один файл = одна кампания».",
    };
  }
  if (typeof count !== "number" || !Number.isInteger(count) || count < 0) {
    return {
      allowed: false,
      state: "pending",
      title: "Количество кампаний пока не определено",
      description: "Дождитесь завершения чтения файла.",
    };
  }
  if (count === 0) {
    return {
      allowed: false,
      state: "missing",
      title: "Кампания в файле не обнаружена",
      description: "Проверьте обязательные поля и загрузите исправленный файл.",
    };
  }
  return {
    allowed: false,
    state: "multiple",
    title: "В файле обнаружено несколько кампаний",
    description: "Каждую кампанию нужно загрузить отдельным файлом. Автоматически разделять файл мы не будем.",
  };
}

export function uploadCanProceedToValidation(
  upload: Pick<CampaignUpload, "status" | "detected_campaigns_n">,
): boolean {
  return upload.status.code === "parsed" && guardSingleCampaign(upload.detected_campaigns_n).allowed;
}

export type ValidationTopStatusCode = "checking" | "ready" | "warning" | "blocked" | "unsupported";
export type ValidationTopStatusTone = "neutral" | "accent" | "warning" | "danger";

export interface ValidationTopStatus {
  code: ValidationTopStatusCode;
  label: string;
  description: string;
  tone: ValidationTopStatusTone;
  canContinue: boolean;
}

export function getValidationTopStatus(
  validation: Pick<
    ValidationResult,
    "status" | "campaigns" | "blocking_errors" | "warnings" | "job_creation_allowed"
  >,
): ValidationTopStatus {
  if (validation.status.code === "running") {
    return {
      code: "checking",
      label: "Кампания проверяется",
      description: "Проверяем структуру файла и доступность расчета.",
      tone: "neutral",
      canContinue: false,
    };
  }

  const campaignGuard = guardSingleCampaign(validation.campaigns.length);
  if (
    validation.status.code === "invalid"
    || validation.blocking_errors.length > 0
    || validation.warnings.some((issue) => issue.severity === "blocking")
    || !validation.job_creation_allowed
    || !campaignGuard.allowed
  ) {
    return {
      code: "blocked",
      label: "Кампанию нужно исправить",
      description: campaignGuard.state === "multiple"
        ? campaignGuard.description
        : "Исправьте блокирующие замечания и загрузите файл заново.",
      tone: "danger",
      canContinue: false,
    };
  }

  if (validation.status.code === "valid" && validation.warnings.length > 0) {
    return {
      code: "warning",
      label: "Кампанию можно рассчитать, но есть замечания",
      description: "Расчет разрешен, но перед запуском изучите замечания.",
      tone: "warning",
      canContinue: true,
    };
  }

  if (validation.status.code === "valid") {
    return {
      code: "ready",
      label: "Кампания готова к расчету",
      description: "Блокирующих замечаний не обнаружено.",
      tone: "accent",
      canContinue: true,
    };
  }

  return {
    code: "unsupported",
    label: "Статус проверки недоступен",
    description: "Не удалось подтвердить результат проверки. Повторите загрузку файла.",
    tone: "danger",
    canContinue: false,
  };
}

export type NewCalculationScenarioId = "S01" | "S02" | "S03" | "S04" | "S05" | "S06";
export type ScenarioRole = "source" | "control" | "benchmark" | "adaptive";

export interface NewCalculationScenarioDefinition {
  id: NewCalculationScenarioId;
  number: string;
  title: string;
  description: string;
  role: ScenarioRole;
  badge: string | null;
}

export const NEW_CALCULATION_SCENARIOS: readonly NewCalculationScenarioDefinition[] = [
  {
    id: "S01",
    number: "Сценарий 1",
    title: "Как загружено",
    description: "Исходный медиаплан остается без изменений.",
    role: "source",
    badge: "Исходный план",
  },
  {
    id: "S02",
    number: "Сценарий 2",
    title: "Равномерно по всем связкам",
    description: "Общий бюджет поровну распределяется между исходными связками гео и каналов.",
    role: "control",
    badge: "Контрольный сценарий",
  },
  {
    id: "S03",
    number: "Сценарий 3",
    title: "Гео выровнены внутри каналов",
    description: "Бюджет каждого канала сохраняется, а гео внутри канала выравниваются.",
    role: "control",
    badge: "Контрольный сценарий",
  },
  {
    id: "S04",
    number: "Сценарий 4",
    title: "Каналы выровнены внутри гео",
    description: "Бюджет каждого гео сохраняется, а каналы внутри гео выравниваются.",
    role: "control",
    badge: "Контрольный сценарий",
  },
  {
    id: "S05",
    number: "Сценарий 5",
    title: "Самый устойчивый план",
    description: "Стремится уменьшить серьезность замечаний и удержать план в знакомой исторической зоне.",
    role: "benchmark",
    badge: "Ориентир по устойчивости",
  },
  {
    id: "S06",
    number: "Сценарий 6",
    title: "Адаптивный поиск",
    description: "Перебирает варианты распределения между исходными связками и проверяет их одной и той же моделью.",
    role: "adaptive",
    badge: "Поиск с проверкой устойчивости",
  },
];

export const SCENARIO_RECOMMENDATION_RULES = [
  "Сценарии, которые нельзя корректно рассчитать, исключаются из сравнения.",
  "Варианты с блокирующим выходом за проверенные границы не рекомендуются автоматически.",
  "При сравнении учитывается качество применения модели.",
  "Ожидаемый дополнительный оборот сравнивается только среди допустимых сценариев.",
  "Выбранный вариант показывается рядом со сценарием 5 — ориентиром по устойчивости.",
] as const;

export interface ScenarioInvariantSnapshot {
  totalBudgetRub: number;
  startDate: string;
  endDate: string;
  channels: readonly string[];
  geographies: readonly string[];
  existingCellsRule: string;
}

export function buildScenarioInvariantSnapshot(
  campaign: Pick<
    CampaignPreview,
    "uploaded_budget_rub" | "start_date" | "end_date" | "channels" | "geographies"
  >,
): ScenarioInvariantSnapshot {
  return {
    totalBudgetRub: campaign.uploaded_budget_rub,
    startDate: campaign.start_date,
    endDate: campaign.end_date,
    channels: [...campaign.channels],
    geographies: [...campaign.geographies],
    existingCellsRule: "Новые каналы, гео и связки гео × канал не добавляются.",
  };
}

export interface SafeIssueAffectedGroups {
  campaigns: readonly string[];
  segments: readonly string[];
  channels: readonly string[];
  geographies: readonly string[];
  geoChannelPairs: readonly string[];
  targets: readonly string[];
  sourceRows: readonly number[];
}

const TARGET_LABELS: Readonly<Record<string, string>> = {
  turnover_per_user: "Оборот на пользователя",
};

function uniqueText(values: readonly string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

export function groupIssueAffectedEntities(
  issue: ValidationIssue,
  campaigns: readonly Pick<CampaignPreview, "campaign_id" | "campaign_name">[],
): SafeIssueAffectedGroups {
  const campaignNames = new Map(campaigns.map((campaign) => [campaign.campaign_id, campaign.campaign_name]));
  const targetOrdinals = new Map<string, number>();

  const targets = uniqueText(issue.affected_cells.map((cell) => cell.target)).map((target) => {
    const knownLabel = TARGET_LABELS[target];
    if (knownLabel) return knownLabel;
    const ordinal = targetOrdinals.size + 1;
    targetOrdinals.set(target, ordinal);
    return `Показатель ${ordinal} — название не поддерживается`;
  });

  const affectedCampaigns = uniqueText(
    issue.affected_cells.map((cell) => (
      cell.campaign_id ? campaignNames.get(cell.campaign_id) ?? "Кампания" : ""
    )),
  );
  if (
    affectedCampaigns.length === 0
    && campaigns.length === 1
    && (issue.scope === "upload" || issue.scope === "row" || issue.scope === "campaign")
  ) {
    affectedCampaigns.push(campaigns[0].campaign_name);
  }

  return {
    campaigns: affectedCampaigns,
    segments: uniqueText(issue.affected_cells.map((cell) => cell.segment)),
    channels: uniqueText(issue.affected_cells.map((cell) => cell.channel)),
    geographies: uniqueText(issue.affected_cells.map((cell) => cell.geo)),
    geoChannelPairs: uniqueText(
      issue.affected_cells.map((cell) => {
        const geo = cell.geo.trim();
        const channel = cell.channel.trim();
        return geo && channel ? `${geo} × ${channel}` : "";
      }),
    ),
    targets,
    sourceRows: [...new Set(issue.source_row_ids)].sort((left, right) => left - right),
  };
}
