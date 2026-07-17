import type { CalculationHistoryV1 } from "../shared/api/generated/calculation-history-v1";
import type { HelpCatalogV1 } from "../shared/api/generated/help-catalog-v1";
import type { ModelOverviewV1 } from "../shared/api/generated/model-overview-v1";
import type { WorkspaceHomeV1 } from "../shared/api/generated/workspace-home-v1";

export const SYNTHETIC_NAVIGATION_BADGE = "Демонстрационные данные";

export function createWorkspaceHomeFixture(): WorkspaceHomeV1 {
  return {
    contract_name: "workspace_home_v1",
    schema_version: "1.0.0",
    record_origin: "synthetic_fixture",
    summary: {
      running: 1,
      queued: 0,
      completed_30d: 1,
      failed_30d: 1,
    },
    active_calculations: [
      {
        job_id: "job_000000000001",
        campaign_name: "Демонстрационная активная кампания",
        status: { code: "running", display_text: "Выполняется" },
        current_stage: {
          stage_id: "P04",
          title: "Рассчитываем контрольные сценарии",
          status: "active",
          display_text: "Идет расчет сценариев",
        },
        created_at_utc: "2026-07-17T08:00:00Z",
        progress_path: "/calculations/job_000000000001/progress",
        can_cancel: true,
        display_text: "Расчет выполняется",
      },
    ],
    recent_calculations: [
      {
        job_id: "job_000000000002",
        campaign_name: "Демонстрационная завершенная кампания",
        campaign_period: { start_date: "2026-08-01", end_date: "2026-08-31" },
        total_budget_rub: 12_000_000,
        created_at_utc: "2026-07-16T08:00:00Z",
        completed_at_utc: "2026-07-16T08:10:00Z",
        status: { code: "succeeded", display_text: "Расчет завершен" },
        result_available: true,
        report_available: true,
        result_path: "/calculations/job_000000000002/result",
        progress_path: "/calculations/job_000000000002/progress",
        warnings_count: 0,
      },
      {
        job_id: "job_000000000003",
        campaign_name: "Демонстрационная кампания с ошибкой",
        campaign_period: null,
        total_budget_rub: null,
        created_at_utc: "2026-07-15T08:00:00Z",
        completed_at_utc: "2026-07-15T08:02:00Z",
        status: { code: "failed", display_text: "Расчет завершился с ошибкой" },
        result_available: false,
        report_available: false,
        result_path: null,
        progress_path: "/calculations/job_000000000003/progress",
        warnings_count: null,
      },
    ],
    model: {
      status: { code: "available", display_text: "Модель доступна" },
      model_id: "pkg_1111111111111111_2222222222222222",
      display_name: "Демонстрационная MMM",
      version: "run_synthetic_v1",
      published_at_utc: "2026-07-15T11:00:00Z",
      training_period: { start_date: "2023-01-01", end_date: "2025-12-31" },
      supported_scope: {
        segments: ["ТС5"],
        channels: ["ТВ", "Онлайн-видео"],
        targets: ["incremental_turnover"],
        geographies_n: 5,
      },
      description: "Исследовательская модель для прогноза и распределения заданного бюджета.",
      details_path: "/model",
    },
    quick_actions: [
      {
        action_id: "new_calculation",
        title: "Новый расчет",
        description: "Загрузить будущую кампанию и запустить оценку.",
        path: "/calculations/new",
      },
      {
        action_id: "calculation_history",
        title: "История расчетов",
        description: "Найти ранее запущенную кампанию и ее результат.",
        path: "/calculations",
      },
      {
        action_id: "model_overview",
        title: "О модели",
        description: "Посмотреть область применения и ограничения модели.",
        path: "/model",
      },
      {
        action_id: "help_catalog",
        title: "Справка",
        description: "Разобраться в сценариях, метриках и предупреждениях.",
        path: "/help",
      },
    ],
    warnings: [
      {
        code: "recent_calculation_failures",
        severity: "warning",
        title: "Есть незавершенные расчеты",
        display_text: "За последние 30 дней есть расчет с ошибкой.",
        recommended_action: "Откройте историю и проверьте нужную кампанию.",
        path: "/calculations",
      },
    ],
    updated_at_utc: "2026-07-17T12:00:00Z",
  };
}

export function createCalculationHistoryFixture(): CalculationHistoryV1 {
  return {
    contract_name: "calculation_history_v1",
    schema_version: "1.0.0",
    record_origin: "synthetic_fixture",
    summary: {
      all: 3,
      active: 1,
      succeeded: 1,
      failed: 1,
      cancelled: 0,
      timed_out: 0,
    },
    filters: {
      status: null,
      search: null,
      created_from: null,
      created_to: null,
      sort: "created_desc",
    },
    pagination: {
      page: 1,
      page_size: 25,
      total_items: 3,
      total_pages: 1,
    },
    items: [
      {
        job_id: "job_000000000001",
        campaign_name: "Демонстрационная активная кампания",
        created_at_utc: "2026-07-17T08:00:00Z",
        completed_at_utc: null,
        status: "running",
        status_display_text: "Выполняется",
        campaign_period: { start_date: "2026-09-01", end_date: "2026-09-30" },
        total_budget_rub: 8_000_000,
        segments: ["ТС5"],
        channels_n: 2,
        geographies_n: 5,
        result_available: false,
        report_available: false,
        progress_path: "/calculations/job_000000000001/progress",
        result_path: null,
        warnings_count: 0,
      },
      {
        job_id: "job_000000000002",
        campaign_name: "Демонстрационная завершенная кампания",
        created_at_utc: "2026-07-16T08:00:00Z",
        completed_at_utc: "2026-07-16T08:10:00Z",
        status: "succeeded",
        status_display_text: "Расчет завершен",
        campaign_period: { start_date: "2026-08-01", end_date: "2026-08-31" },
        total_budget_rub: 12_000_000,
        segments: ["ТС5"],
        channels_n: 2,
        geographies_n: 5,
        result_available: true,
        report_available: true,
        progress_path: "/calculations/job_000000000002/progress",
        result_path: "/calculations/job_000000000002/result",
        warnings_count: 0,
      },
      {
        job_id: "job_000000000003",
        campaign_name: "Демонстрационная кампания с ошибкой",
        created_at_utc: "2026-07-15T08:00:00Z",
        completed_at_utc: "2026-07-15T08:02:00Z",
        status: "failed",
        status_display_text: "Расчет завершился с ошибкой",
        campaign_period: null,
        total_budget_rub: null,
        segments: null,
        channels_n: null,
        geographies_n: null,
        result_available: false,
        report_available: false,
        progress_path: "/calculations/job_000000000003/progress",
        result_path: null,
        warnings_count: null,
      },
    ],
    updated_at_utc: "2026-07-17T12:00:00Z",
  };
}

export function createModelOverviewFixture(): ModelOverviewV1 {
  return {
    contract_name: "model_overview_v1",
    schema_version: "1.0.0",
    record_origin: "synthetic_fixture",
    active_model: {
      status: { code: "available", display_text: "Модель доступна" },
      model_id: "pkg_1111111111111111_2222222222222222",
      display_name: "Демонстрационная MMM",
      version: "run_synthetic_v1",
      published_at_utc: "2026-07-15T11:00:00Z",
      framework: "Bayesian MMM на PyMC",
      purpose: "Прогноз дополнительного медиаэффекта и сравнение распределений бюджета.",
      training_period: { start_date: "2023-01-01", end_date: "2025-12-31" },
      supported_scope: {
        segments: ["ТС5"],
        channels: ["ТВ", "Онлайн-видео"],
        targets: ["incremental_turnover"],
        geographies_n: 5,
        capability_cells_n: 10,
        allowed_use_counts: { primary: 6, caution: 2, diagnostic: 1, unavailable: 1 },
      },
      description: "Исследовательская модель проверяет кампанию в поддерживаемой области.",
    },
    capabilities: [
      {
        capability_id: "incremental_effect_forecast",
        title: "Прогноз дополнительного эффекта",
        status: "available",
        description: "Оценивает эффект кампании относительно варианта без нее.",
      },
      {
        capability_id: "six_scenarios",
        title: "Сравнение S1-S6",
        status: "available",
        description: "Сравнивает исходный план и пять вариантов распределения.",
      },
      {
        capability_id: "budget_allocation",
        title: "Распределение бюджета",
        status: "available",
        description: "Показывает распределение бюджета по каналам и географиям.",
      },
      {
        capability_id: "safe_recommendation",
        title: "Рекомендация с ограничениями надежности",
        status: "conditional",
        description: "Выбирает распределение с учетом исторической зоны.",
      },
      {
        capability_id: "marketer_report",
        title: "Отчет для маркетолога",
        status: "available",
        description: "Формирует Excel с результатом и предупреждениями.",
      },
    ],
    data_requirements: [
      {
        requirement_id: "file_format",
        title: "Формат файла",
        required: true,
        description: "Используйте табличный файл с заголовками колонок.",
        accepted_values: ["CSV", "XLSX"],
      },
    ],
    methodology: [
      { method_id: "carryover", title: "Перенос эффекта во времени", summary: "Часть отклика проявляется после размещения." },
      { method_id: "saturation", title: "Насыщение", summary: "Отдача от расходов может замедляться." },
      { method_id: "uncertainty", title: "Неопределенность", summary: "Результат публикуется диапазоном P10-P90." },
      { method_id: "counterfactual_forecast", title: "Сравнение без кампании", summary: "Оценивается дополнительный медиавклад." },
      { method_id: "scenario_search", title: "Поиск распределения", summary: "S6 сравнивает рассчитанные варианты." },
      { method_id: "reliability_guardrails", title: "Ограничения надежности", summary: "Историческая поддержка ограничивает автоматическое перераспределение." },
    ],
    limitations: [
      {
        code: "reliability_score_unavailable",
        status: "unavailable",
        title: "Нет единого балла надежности",
        display_text: "Надежность объясняется отдельными признаками.",
        recommended_action: "Читайте диапазон и предупреждения.",
      },
      {
        code: "daily_scenario_plans_unavailable",
        status: "unavailable",
        title: "Дневные планы недоступны",
        display_text: "Дневная раскладка сценариев пока не публикуется.",
        recommended_action: "Используйте доступное распределение.",
      },
      {
        code: "map_unavailable",
        status: "unavailable",
        title: "Карта недоступна",
        display_text: "Распределение доступно без карты.",
        recommended_action: "Используйте таблицу географий.",
      },
      {
        code: "working_media_plan_xlsx_unavailable",
        status: "unavailable",
        title: "Рабочий медиаплан недоступен",
        display_text: "Отдельный редактируемый файл пока не публикуется.",
        recommended_action: "Используйте отчет для маркетолога.",
      },
      {
        code: "allocation_only",
        status: "active",
        title: "Рекомендация только по распределению",
        display_text: "Система не принимает решение о запуске кампании.",
        recommended_action: "Сопоставьте прогноз с бизнес-целями.",
      },
    ],
    versions: [
      {
        model_id: "pkg_1111111111111111_2222222222222222",
        model_run_id: "run_synthetic_v1",
        registered_at_utc: "2026-07-15T10:00:00Z",
        package_stage: "posterior_ready",
        activation_status: "preprod_restricted",
        status: "active",
        source: "registry_registration",
      },
      {
        model_id: "pkg_3333333333333333_4444444444444444",
        model_run_id: "run_synthetic_v0",
        registered_at_utc: "2026-07-10T10:00:00Z",
        package_stage: "posterior_ready",
        activation_status: "registered",
        status: "registered",
        source: "registry_registration",
      },
    ],
    artifacts: [],
    updated_at_utc: "2026-07-17T12:00:00Z",
  };
}

const helpArticles = [
  ["getting_started", "quick_start", "Как начать", "Первый расчет"],
  ["data_preparation", "campaign_file_fields", "Подготовка данных", "Поля файла кампании"],
  ["scenarios", "scenarios_s1_s6", "Сценарии S1-S6", "Зачем нужны шесть сценариев"],
  ["result_reading", "effect_and_uncertainty", "Как читать результат", "Эффект и неопределенность"],
  ["reliability", "reliability_and_support", "Надежность", "Историческая зона"],
  ["media_plan", "media_plan_distribution", "Медиаплан", "Распределение бюджета"],
  ["report", "marketer_report", "Отчет", "Отчет для маркетолога"],
  ["common_errors", "input_and_calculation_errors", "Частые ошибки", "Что делать при ошибке"],
  ["limitations", "current_limitations", "Ограничения", "Текущие границы"],
] as const;

export function createHelpCatalogFixture(): HelpCatalogV1 {
  return {
    contract_name: "help_catalog_v1",
    schema_version: "1.0.0",
    record_origin: "synthetic_fixture",
    sections: helpArticles.map(([section_id, article_id, sectionTitle, articleTitle], index) => ({
      section_id,
      order: index + 1,
      title: sectionTitle,
      articles: [
        {
          article_id,
          title: articleTitle,
          summary: `Демонстрационная статья: ${articleTitle}.`,
          body: [
            {
              block_type: "paragraph" as const,
              text: `Демонстрационное объяснение раздела «${sectionTitle}».`,
            },
            {
              block_type: "note" as const,
              tone: "info" as const,
              title: "Обратите внимание",
              text: "Используйте опубликованные сведения и учитывайте ограничения.",
            },
          ],
          related_routes: index === 0 ? ["/calculations/new" as const] : ["/help" as const],
          related_article_ids: [],
          keywords: [sectionTitle.toLocaleLowerCase(), articleTitle.toLocaleLowerCase()],
        },
      ],
    })) as unknown as HelpCatalogV1["sections"],
    updated_at_utc: "2026-07-17T12:00:00Z",
  };
}
