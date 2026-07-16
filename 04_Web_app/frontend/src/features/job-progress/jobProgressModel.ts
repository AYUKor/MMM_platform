import type {
  JobProgressViewV1,
  ProductStage,
  ProgressError,
  Scenario6Progress,
} from "../../shared/api/generated/job-progress-view-v1";
import type { MMMFactCatalogV1 } from "../../shared/api/generated/mmm-fact-catalog-v1";

export type StatusTone = "neutral" | "accent" | "warning" | "danger";
export type MMMFact = MMMFactCatalogV1["facts"][number];

const terminalStatuses = new Set<JobProgressViewV1["job_status"]["code"]>([
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
]);

const jobStatusLabels: Record<JobProgressViewV1["job_status"]["code"], string> = {
  queued: "В очереди",
  running: "Выполняется",
  cancel_requested: "Останавливается",
  succeeded: "Готово",
  failed: "Ошибка",
  cancelled: "Отменено",
  timed_out: "Не завершено вовремя",
};

const stageStatusLabels: Record<ProductStage["status"], string> = {
  pending: "Ожидает",
  active: "Выполняется",
  completed: "Завершен",
  warning: "Завершен с замечанием",
  failed: "Ошибка",
  skipped: "Не выполнялся",
};

const scenario6Labels: Record<Scenario6Progress["status"], string> = {
  pending: "Поиск вариантов еще не начался",
  running: "Идет проверка вариантов распределения",
  completed: "Поиск вариантов завершен",
  unavailable: "Адаптивный поиск не применялся",
  failed: "Не удалось завершить поиск вариантов",
};

const numberFormatter = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const timeFormatter = new Intl.DateTimeFormat("ru-RU", {
  hour: "2-digit",
  minute: "2-digit",
});

export function isTerminalJobStatus(
  status: JobProgressViewV1["job_status"]["code"] | undefined,
): boolean {
  return status !== undefined && terminalStatuses.has(status);
}

export function jobStatusLabel(status: JobProgressViewV1["job_status"]["code"]): string {
  return jobStatusLabels[status];
}

export function jobStatusTone(status: JobProgressViewV1["job_status"]["code"]): StatusTone {
  if (status === "succeeded") return "accent";
  if (status === "failed" || status === "timed_out") return "danger";
  if (status === "queued" || status === "running" || status === "cancel_requested") {
    return "warning";
  }
  return "neutral";
}

export function stageStatusLabel(status: ProductStage["status"]): string {
  return stageStatusLabels[status];
}

export function currentStage(view: JobProgressViewV1): ProductStage {
  return view.stages.find((stage) => stage.stage_id === view.current_stage_id) ?? view.stages[0];
}

export function currentStatusCopy(view: JobProgressViewV1): {
  title: string;
  description: string;
} {
  const activeStage = currentStage(view);
  switch (view.job_status.code) {
    case "queued":
      return {
        title: "Расчет ожидает запуска",
        description: view.queue.display_text,
      };
    case "running":
      return { title: activeStage.title, description: activeStage.display_text };
    case "cancel_requested":
      return {
        title: "Расчет останавливается",
        description: "Запрос принят. Текущий этап завершится безопасно.",
      };
    case "succeeded":
      return { title: "Расчет завершен", description: "Результат готов к просмотру." };
    case "failed":
      return {
        title: "Расчет завершился с ошибкой",
        description: "Ниже показано, что произошло и что можно сделать.",
      };
    case "cancelled":
      return {
        title: "Расчет отменен",
        description: "Расчет остановлен и новый результат не сформирован.",
      };
    case "timed_out":
      return {
        title: "Расчет не завершен вовремя",
        description: "Расчет остановлен после превышения допустимого времени.",
      };
  }
}

export function queuePositionText(view: JobProgressViewV1): string | null {
  if (view.job_status.code !== "queued") return null;
  if (view.queue.position === null) return "Положение в очереди уточняется";
  if (view.queue.queued_jobs_total === null) {
    return `Позиция в очереди: ${formatCount(view.queue.position)}`;
  }
  return `Позиция в очереди: ${formatCount(view.queue.position)} из ${formatCount(view.queue.queued_jobs_total)}`;
}

export function scenario6StatusText(status: Scenario6Progress["status"]): string {
  return scenario6Labels[status];
}

export function formatCount(value: number): string {
  return numberFormatter.format(value);
}

export function formatCounterPair(current: number, total: number): string {
  return `${formatCount(current)} / ${formatCount(total)}`;
}

export function formatStageTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : timeFormatter.format(parsed);
}

export function sortProgressErrors(errors: readonly ProgressError[]): ProgressError[] {
  return [...errors].sort((left, right) => {
    if (left.blocking !== right.blocking) return left.blocking ? -1 : 1;
    if (left.severity !== right.severity) return left.severity === "error" ? -1 : 1;
    return left.stage_id.localeCompare(right.stage_id);
  });
}

export function selectFactForJob(
  catalog: MMMFactCatalogV1 | undefined,
  jobId: string,
): MMMFact | null {
  if (!catalog || catalog.facts.length === 0 || jobId.length === 0) return null;
  let hash = 2_166_136_261;
  for (let index = 0; index < jobId.length; index += 1) {
    hash ^= jobId.charCodeAt(index);
    hash = Math.imul(hash, 16_777_619);
  }
  return catalog.facts[(hash >>> 0) % catalog.facts.length] ?? null;
}
