export type ResultCopyTone = "positive" | "neutral" | "warning" | "danger";

export type ResultStatusDomain =
  | "calculation"
  | "campaignScale"
  | "cellSupport"
  | "optimizer"
  | "businessDecision"
  | "quality"
  | "recommendationType"
  | "plan"
  | "scenario6Run";

export interface ResultStatusCopy {
  label: string;
  description: string;
  tone: ResultCopyTone;
  known: boolean;
}

export interface ResultWarningCopy {
  title: string;
  meaning: string;
  action: string;
  tone: ResultCopyTone;
  known: boolean;
}

export interface ScenarioCopy {
  number: string;
  title: string;
  description: string;
  badge: string | null;
  available: boolean;
  known: boolean;
}

export interface GateReasonCopy {
  label: string;
  meaning: string;
  action: string;
  tone: ResultCopyTone;
  known: boolean;
}

type KnownStatusCopy = Omit<ResultStatusCopy, "known">;
type KnownWarningCopy = Omit<ResultWarningCopy, "known">;
type KnownScenarioCopy = Omit<ScenarioCopy, "available" | "known">;
type KnownGateReasonCopy = Omit<GateReasonCopy, "known">;

const STATUS_COPY: Record<ResultStatusDomain, Record<string, KnownStatusCopy>> = {
  calculation: {
    calculated: {
      label: "Расчет готов",
      description: "Доступные показатели рассчитаны сервисом и готовы к просмотру.",
      tone: "positive",
    },
    partially_calculated: {
      label: "Рассчитано частично",
      description: "Часть бюджета или связок не покрыта моделью. Смотрите предупреждения перед использованием результата.",
      tone: "warning",
    },
    not_calculated: {
      label: "Расчет не выполнен",
      description: "Показатели недоступны. Не используйте этот результат для решения по медиаплану.",
      tone: "danger",
    },
  },
  campaignScale: {
    within_historical_p95: {
      label: "Масштаб сопоставим с историей",
      description: "Бюджет кампании находится в обычном для модели историческом диапазоне.",
      tone: "positive",
    },
    between_historical_p95_p99: {
      label: "Крупная кампания",
      description: "Похожие масштабы встречались редко, поэтому результат требует повышенного внимания.",
      tone: "warning",
    },
    between_historical_p99_and_robust_upper: {
      label: "Очень крупная кампания",
      description: "Масштаб близок к верхней границе наблюдаемой истории. Проверяйте неопределенность и ограничения.",
      tone: "warning",
    },
    above_historical_robust_upper: {
      label: "Масштаб вне надежной зоны",
      description: "Кампания превышает устойчиво наблюдавшийся диапазон. Автоматическое решение небезопасно.",
      tone: "danger",
    },
    benchmark_unavailable: {
      label: "Сравнение с историей недоступно",
      description: "Сервис не передал достаточную историческую опору для оценки масштаба.",
      tone: "warning",
    },
  },
  cellSupport: {
    within_p95: {
      label: "В надежной наблюдаемой зоне",
      description: "Связки каналов и географий находятся внутри устойчиво наблюдавшегося диапазона.",
      tone: "positive",
    },
    between_p95_p99: {
      label: "Повышенная неопределенность",
      description: "Часть связок встречалась редко. Результат допустим с дополнительной проверкой.",
      tone: "warning",
    },
    above_p99_within_robust_upper: {
      label: "Нужна ручная проверка",
      description: "Есть редкие связки у верхней границы наблюдаемой зоны.",
      tone: "warning",
    },
    above_robust_upper: {
      label: "Есть связки вне надежной зоны",
      description: "Автоматически перераспределять бюджет по этим связкам нельзя.",
      tone: "danger",
    },
    not_evaluated: {
      label: "Надежность связок не оценена",
      description: "Нет подтвержденной оценки покрытия для автоматического решения.",
      tone: "warning",
    },
  },
  optimizer: {
    best_safe_available: {
      label: "Безопасный вариант найден",
      description: "Сервис нашел вариант, прошедший действующие ограничения модели и медиаплана.",
      tone: "positive",
    },
    partial_safe_available: {
      label: "Доступен частичный вариант",
      description: "Безопасное автоматическое распределение найдено только для части бюджета или связок.",
      tone: "warning",
    },
    no_safe_candidate: {
      label: "Безопасный вариант не найден",
      description: "Ни один автоматический вариант не прошел все ограничения. Нужна ручная проверка.",
      tone: "warning",
    },
    gate_policy_blocked: {
      label: "Автоматическое перераспределение заблокировано",
      description: "Ограничения модели не разрешают использовать адаптивный вариант автоматически.",
      tone: "danger",
    },
    not_run: {
      label: "Оптимизация не запускалась",
      description: "Адаптивный вариант не рассчитывался; сравнивайте только доступные сценарии.",
      tone: "neutral",
    },
  },
  businessDecision: {
    allocation_only: {
      label: "Только рекомендация по распределению",
      description: "Результат помогает распределить бюджет, но не решает, запускать или отменять кампанию.",
      tone: "warning",
    },
    manual_review_required: {
      label: "Нужно бизнес-решение",
      description: "Перед применением результата требуется ручная оценка владельца кампании.",
      tone: "warning",
    },
    meets_business_hurdle: {
      label: "Заданный бизнес-порог выполнен",
      description: "Расчет прошел настроенный порог, но финальное решение остается за владельцем кампании.",
      tone: "positive",
    },
    below_business_hurdle: {
      label: "Ниже заданного бизнес-порога",
      description: "Расчет не прошел настроенный порог; требуется ручное решение.",
      tone: "warning",
    },
    not_evaluated: {
      label: "Бизнес-решение не оценено",
      description: "Сервис не передал подтвержденную оценку относительно бизнес-порога.",
      tone: "warning",
    },
  },
  quality: {
    reliable: {
      label: "Устойчивая оценка",
      description: "Покрытие и неопределенность допускают использование результата в заявленных границах.",
      tone: "positive",
    },
    elevated_uncertainty: {
      label: "Повышенная неопределенность",
      description: "Результат можно рассматривать, но диапазон возможных значений шире обычного.",
      tone: "warning",
    },
    manual_review_required: {
      label: "Нужна ручная проверка",
      description: "Перед применением результата проверьте покрытие, ограничения и предупреждения.",
      tone: "warning",
    },
    not_for_automatic_reallocation: {
      label: "Не для автоматического перераспределения",
      description: "Расчет можно изучать, но автоматически менять медиаплан по нему нельзя.",
      tone: "danger",
    },
    not_calculated: {
      label: "Оценка недоступна",
      description: "Сервис не сформировал показатели качества для этого состояния.",
      tone: "danger",
    },
  },
  recommendationType: {
    keep_uploaded_plan: {
      label: "Сохранить исходный план",
      description: "Сервис не рекомендует автоматическое перераспределение бюджета.",
      tone: "neutral",
    },
    reallocate_for_reliability: {
      label: "Перераспределить с учетом устойчивости",
      description: "Рекомендация уменьшает риск выхода за надежно наблюдавшиеся границы.",
      tone: "positive",
    },
    reallocate_for_effect: {
      label: "Перераспределить с учетом эффекта",
      description: "Сервис выбрал допустимый вариант по ожидаемому эффекту и ограничениям.",
      tone: "positive",
    },
    partial_safe_plan: {
      label: "Применить только подтвержденную часть",
      description: "Автоматическая рекомендация покрывает не весь бюджет или не все связки.",
      tone: "warning",
    },
    manual_review: {
      label: "Проверить медиаплан вручную",
      description: "Подтвержденной автоматической рекомендации нет.",
      tone: "warning",
    },
  },
  plan: {
    recommended_media_plan: {
      label: "Рекомендованный медиаплан",
      description: "План сформирован сервисом с учетом доступных ограничений.",
      tone: "positive",
    },
    full_plan_partial_model_coverage: {
      label: "Полный план, частичное покрытие модели",
      description: "В плане сохранен весь бюджет, но модель оценивает не все его части.",
      tone: "warning",
    },
    partial_safe_plan: {
      label: "Частичный безопасный план",
      description: "Часть бюджета остается без автоматического распределения и требует ручного решения.",
      tone: "warning",
    },
    no_automatic_plan: {
      label: "Автоматический план недоступен",
      description: "Используйте исходный план или подготовьте решение вручную после проверки ограничений.",
      tone: "danger",
    },
  },
  scenario6Run: {
    completed_best_safe: {
      label: "Безопасный вариант найден",
      description: "Адаптивный поиск завершен, и допустимый вариант прошел финальную проверку сервиса.",
      tone: "positive",
    },
    completed_partial_safe: {
      label: "Найден частичный вариант",
      description: "Адаптивный поиск подтвердил только часть автоматического распределения.",
      tone: "warning",
    },
    completed_no_safe_candidate: {
      label: "Допустимый вариант не найден",
      description: "Поиск завершен, но ни один вариант не прошел все ограничения.",
      tone: "warning",
    },
    gate_policy_blocked: {
      label: "Поиск заблокирован ограничениями",
      description: "Модель не разрешает формировать автоматическую рекомендацию для этого состояния.",
      tone: "danger",
    },
    not_run: {
      label: "Поиск не запускался",
      description: "Для этого расчета нет результата адаптивного поиска.",
      tone: "neutral",
    },
  },
};

const WARNING_COPY: Record<string, KnownWarningCopy> = {
  sanitized_fixture_not_production_evidence: {
    title: "Демонстрационные данные",
    meaning: "Этот результат предназначен только для проверки интерфейса и не является результатом реальной кампании.",
    action: "Не используйте его для бизнес-решений и не выдавайте за production-расчет.",
    tone: "neutral",
  },
  model_preprod_restricted: {
    title: "Модель работает в предварительном режиме",
    meaning: "Расчет доступен для проверки продукта, но модель еще не допущена к production-применению.",
    action: "Используйте результат только в согласованных preprod-сценариях.",
    tone: "warning",
  },
  missing_or_failed_oot_validation: {
    title: "Нет подтвержденной проверки на отложенном периоде",
    meaning: "У модели отсутствует успешная независимая проверка качества на данных вне обучения.",
    action: "Не используйте результат как production-доказательство до завершения и приемки этой проверки.",
    tone: "danger",
  },
  missing_or_failed_historical_replay: {
    title: "Нет подтвержденного исторического воспроизведения",
    meaning: "Модель не прошла обязательную проверку на завершенных исторических кампаниях.",
    action: "Не активируйте автоматическое применение до успешной проверки и согласования результатов.",
    tone: "danger",
  },
  unmodeled_budget_present: {
    title: "Часть бюджета вне покрытия модели",
    meaning: "Для части каналов или связок модель не рассчитывает эффект.",
    action: "Сохраните эту часть в медиаплане отдельно и проверьте ее вручную.",
    tone: "warning",
  },
  cell_support_risk: {
    title: "Есть слабо подтвержденные связки",
    meaning: "Некоторые сочетания каналов и географий редко встречались в исторических данных.",
    action: "Проверьте отмеченные строки медиаплана перед изменением бюджета.",
    tone: "warning",
  },
  gate_policy_blocked: {
    title: "Автоматическое перераспределение недоступно",
    meaning: "Действующие ограничения модели заблокировали адаптивный вариант.",
    action: "Не применяйте автоматический план; используйте доступный benchmark или ручное решение.",
    tone: "danger",
  },
  no_safe_candidate: {
    title: "Безопасный автоматический вариант не найден",
    meaning: "Ни один найденный вариант не прошел все проверки модели и медиаплана.",
    action: "Сохраните исходный план или проверьте распределение вручную.",
    tone: "warning",
  },
  not_run: {
    title: "Адаптивный поиск не запускался",
    meaning: "Для этого расчета нет автоматического варианта перераспределения.",
    action: "Используйте только рассчитанные сценарии и не делайте выводов об оптимальном плане.",
    tone: "neutral",
  },
  quality_elevated_uncertainty: {
    title: "Неопределенность выше обычной",
    meaning: "Часть оценки опирается на редкие наблюдения, поэтому возможный диапазон результата шире.",
    action: "Смотрите интервалы, а не только центральную оценку, и проверьте медиаплан вручную.",
    tone: "warning",
  },
  quality_manual_review_required: {
    title: "Требуется ручная проверка качества",
    meaning: "Сервис обнаружил ограничения, которые не позволяют применить результат автоматически.",
    action: "Проверьте покрытие и предупреждения до изменения медиаплана.",
    tone: "warning",
  },
  quality_not_for_automatic_reallocation: {
    title: "Расчет не подходит для автоматического перераспределения",
    meaning: "Показатели можно изучать, но надежность недостаточна для автоматического изменения бюджета.",
    action: "Используйте результат только как диагностический и примите решение вручную.",
    tone: "danger",
  },
  quality_not_calculated: {
    title: "Оценка качества не рассчитана",
    meaning: "Для этого состояния нет подтвержденного результата качества.",
    action: "Не используйте его для изменения медиаплана.",
    tone: "danger",
  },
  business_hurdle_not_approved: {
    title: "Не настроен бизнес-порог",
    meaning: "Результат сравнивает способы распределения бюджета, но не отвечает, стоит ли запускать кампанию.",
    action: "Решение о запуске примите отдельно с учетом маржи, целей и согласованного бизнес-порога.",
    tone: "warning",
  },
};

const WARNING_SEVERITY_COPY: Record<string, KnownStatusCopy> = {
  info: {
    label: "Информация",
    description: "Контекст, который важно учитывать при чтении результата.",
    tone: "neutral",
  },
  caution: {
    label: "Обратите внимание",
    description: "Есть ограничение, которое может повлиять на интерпретацию результата.",
    tone: "warning",
  },
  manual_review: {
    label: "Нужна ручная проверка",
    description: "Не применяйте результат автоматически до проверки ответственным специалистом.",
    tone: "warning",
  },
  blocking: {
    label: "Применение заблокировано",
    description: "Это состояние нельзя использовать для автоматического решения.",
    tone: "danger",
  },
};

const SCENARIO_COPY: Record<string, KnownScenarioCopy> = {
  S01: {
    number: "Сценарий 1",
    title: "Как загрузили",
    description: "Исходный бюджет и распределение остаются без изменений.",
    badge: null,
  },
  S02: {
    number: "Сценарий 2",
    title: "Поровну по всем связкам",
    description: "Бюджет делится поровну между исходными сочетаниями географий и каналов.",
    badge: null,
  },
  S03: {
    number: "Сценарий 3",
    title: "Каналы как были, географии поровну",
    description: "Бюджет каждого канала сохраняется, а внутри канала делится поровну между географиями.",
    badge: null,
  },
  S04: {
    number: "Сценарий 4",
    title: "Географии как были, каналы поровну",
    description: "Бюджет каждой географии сохраняется, а внутри нее делится поровну между каналами.",
    badge: null,
  },
  S05: {
    number: "Сценарий 5",
    title: "Осторожное распределение",
    description: "Консервативный вариант внутри надежной наблюдаемой зоны. Это устойчивый benchmark, а не автоматически лучший план.",
    badge: "Устойчивый benchmark",
  },
  S06: {
    number: "Сценарий 6",
    title: "Адаптивный поиск",
    description: "Вариант, отобранный сервисом после проверки ограничений модели и медиаплана.",
    badge: null,
  },
};

const ACTION_COPY: Record<string, KnownStatusCopy> = {
  increase: {
    label: "Увеличить",
    description: "Рекомендуется увеличить бюджет этой строки.",
    tone: "positive",
  },
  decrease: {
    label: "Уменьшить",
    description: "Рекомендуется уменьшить бюджет этой строки.",
    tone: "warning",
  },
  keep: {
    label: "Без изменения",
    description: "Рекомендуется сохранить бюджет этой строки.",
    tone: "neutral",
  },
};

const GATE_REASON_COPY: Record<string, KnownGateReasonCopy> = {
  OK: {
    label: "Ограничений не выявлено",
    meaning: "Сервис не передал ограничений для этой строки.",
    action: "Дополнительное действие не требуется.",
    tone: "positive",
  },
  SANITIZED_AGGREGATE: {
    label: "Демонстрационная строка",
    meaning: "Значения агрегированы и обезличены для проверки интерфейса.",
    action: "Не используйте эту строку как результат реальной кампании.",
    tone: "neutral",
  },
  UNSUPPORTED_MODEL_CELL: {
    label: "Связка не поддерживается моделью",
    meaning: "Для этого сочетания сегмента, географии и канала нет подтвержденной оценки.",
    action: "Сохраните бюджет отдельно и примите решение вручную.",
    tone: "danger",
  },
  UPSTREAM_DIAGNOSTIC_ONLY: {
    label: "Только диагностическое использование",
    meaning: "Исходная оценка не разрешена для автоматической оптимизации.",
    action: "Не меняйте бюджет автоматически по этой строке.",
    tone: "warning",
  },
  MISSING_UPSTREAM_USE_CASE: {
    label: "Не подтверждено назначение оценки",
    meaning: "Нет явного разрешения использовать исходную оценку для оптимизации.",
    action: "Оставьте решение ручным до уточнения назначения модели.",
    tone: "danger",
  },
  MISSING_ACTIVE_DAYS: {
    label: "Нет данных о длительности истории",
    meaning: "Нельзя проверить, достаточно ли дней наблюдения для канала.",
    action: "Проверьте входные данные перед изменением бюджета.",
    tone: "danger",
  },
  VERY_SHORT_ACTIVE_HISTORY: {
    label: "Слишком короткая история",
    meaning: "Канал наблюдался недостаточно долго для надежной автоматической оценки.",
    action: "Используйте результат только как диагностический.",
    tone: "danger",
  },
  SHORT_ACTIVE_HISTORY: {
    label: "Короткая история",
    meaning: "Для канала доступно мало дней наблюдения, поэтому неопределенность выше.",
    action: "Проверяйте изменение бюджета вручную.",
    tone: "warning",
  },
  MISSING_ACTIVE_GEOS: {
    label: "Нет данных о географическом покрытии",
    meaning: "Нельзя проверить, в скольких географиях наблюдался канал.",
    action: "Проверьте покрытие до изменения бюджета.",
    tone: "danger",
  },
  VERY_LOW_GEO_COVERAGE: {
    label: "Очень низкое географическое покрытие",
    meaning: "Оценка опирается на слишком малое число географий.",
    action: "Не применяйте автоматическое увеличение бюджета.",
    tone: "danger",
  },
  LOW_GEO_COVERAGE: {
    label: "Низкое географическое покрытие",
    meaning: "Канал наблюдался в небольшом числе географий.",
    action: "Проверьте переносимость оценки вручную.",
    tone: "warning",
  },
  MISSING_NONZERO_SHARE: {
    label: "Неизвестна плотность наблюдений",
    meaning: "Нет данных, позволяющих оценить регулярность активности канала.",
    action: "Проверьте полноту входных данных.",
    tone: "danger",
  },
  EXTREMELY_SPARSE_MEDIA: {
    label: "Крайне редкие наблюдения",
    meaning: "Активность канала встречается слишком редко для надежной автоматической оценки.",
    action: "Используйте результат только как диагностический.",
    tone: "danger",
  },
  SPARSE_MEDIA: {
    label: "Редкие наблюдения",
    meaning: "Активность канала встречается нерегулярно, поэтому оценка менее устойчива.",
    action: "Проверяйте изменение бюджета вручную.",
    tone: "warning",
  },
  TARGET_POLICY_DIAGNOSTIC_ONLY: {
    label: "Метрика только для диагностики",
    meaning: "Эта метрика не используется как цель автоматического перераспределения.",
    action: "Не делайте по ней самостоятельную рекомендацию по бюджету.",
    tone: "warning",
  },
  TARGET_POLICY_RESTRICTION: {
    label: "Ограничение по целевой метрике",
    meaning: "Политика модели ограничивает автоматическое применение этой оценки.",
    action: "Используйте только разрешенный уровень применения.",
    tone: "warning",
  },
  MISSING_CONTRACTION_EVIDENCE: {
    label: "Нет проверки устойчивости эффекта",
    meaning: "Недостаточно данных, чтобы подтвердить поведение оценки при изменении бюджета.",
    action: "Не увеличивайте бюджет автоматически.",
    tone: "danger",
  },
  UNAVAILABLE_CONTRACTION_EVIDENCE: {
    label: "Проверка устойчивости недоступна",
    meaning: "Часть необходимой проверки эффекта не сформирована.",
    action: "Оставьте решение ручным.",
    tone: "danger",
  },
  POSTERIOR_EXPANDED_EFFECT: {
    label: "Эффект нестабилен при проверке",
    meaning: "Неопределенность оценки увеличилась после дополнительной проверки.",
    action: "Не увеличивайте бюджет автоматически и оцените риск вручную.",
    tone: "warning",
  },
  LOW_CONTRACTION_EFFECT: {
    label: "Слабое подтверждение устойчивости",
    meaning: "Дополнительная проверка недостаточно усилила уверенность в эффекте.",
    action: "Используйте осторожный вариант или ручное решение.",
    tone: "warning",
  },
  FIXED_SATURATION_SHAPE: {
    label: "Форма отклика зафиксирована",
    meaning: "Кривая насыщения задана ограничением для устойчивости модели, а не полностью оценена из данных.",
    action: "Не используйте эту строку для автоматического увеличения бюджета.",
    tone: "warning",
  },
  FIT_LEVEL_CAUTION: {
    label: "Оценка требует осторожности",
    meaning: "Диагностика модели допускает прогноз только с дополнительными ограничениями.",
    action: "Проверяйте изменение бюджета вручную.",
    tone: "warning",
  },
  FIT_LEVEL_DIAGNOSTIC: {
    label: "Оценка только для диагностики",
    meaning: "Диагностика модели не разрешает использовать оценку для автоматической оптимизации.",
    action: "Не меняйте бюджет автоматически.",
    tone: "danger",
  },
};

const UNKNOWN_STATUS: ResultStatusCopy = {
  label: "Статус недоступен",
  description: "Получен неподдерживаемый статус. Не используйте результат для автоматического решения до проверки.",
  tone: "danger",
  known: false,
};

const UNKNOWN_WARNING: ResultWarningCopy = {
  title: "Требуется дополнительная проверка",
  meaning: "Сервис передал предупреждение без поддерживаемого пользовательского описания.",
  action: "Не применяйте результат автоматически и передайте расчет на ручную проверку.",
  tone: "danger",
  known: false,
};

const UNKNOWN_SCENARIO: ScenarioCopy = {
  number: "Сценарий",
  title: "Описание недоступно",
  description: "Сервис передал неподдерживаемый тип сценария. Не сравнивайте его с остальными до проверки.",
  badge: "Нужна проверка",
  available: false,
  known: false,
};

const UNKNOWN_GATE_REASON: GateReasonCopy = {
  label: "Нужна ручная проверка",
  meaning: "Для этой строки действует ограничение без поддерживаемого пользовательского описания.",
  action: "Не применяйте изменение бюджета автоматически.",
  tone: "danger",
  known: false,
};

export function getStatusCopy(domain: ResultStatusDomain, code: string): ResultStatusCopy {
  const copy = STATUS_COPY[domain][code];
  return copy ? { ...copy, known: true } : { ...UNKNOWN_STATUS };
}

export function getQualityCopy(code: string): ResultStatusCopy {
  return getStatusCopy("quality", code);
}

export function getWarningSeverityCopy(severity: string): ResultStatusCopy {
  const copy = WARNING_SEVERITY_COPY[severity];
  return copy ? { ...copy, known: true } : { ...UNKNOWN_STATUS };
}

export function getWarningCopy(code: string): ResultWarningCopy {
  const copy = WARNING_COPY[code];
  return copy ? { ...copy, known: true } : { ...UNKNOWN_WARNING };
}

export function getScenarioCopy(scenarioId: string, available = true): ScenarioCopy {
  const copy = SCENARIO_COPY[scenarioId];
  if (!copy) return { ...UNKNOWN_SCENARIO };

  if (scenarioId === "S06" && !available) {
    return {
      ...copy,
      title: "Адаптивный поиск недоступен",
      description: "Безопасный автоматический вариант не сформирован. Проверьте ограничения и предупреждения расчета.",
      badge: "Недоступно",
      available: false,
      known: true,
    };
  }

  return { ...copy, available, known: true };
}

export function getAllocationActionCopy(action: string): ResultStatusCopy {
  const copy = ACTION_COPY[action];
  return copy ? { ...copy, known: true } : { ...UNKNOWN_STATUS };
}

export function getGateReasonCopy(code: string): GateReasonCopy {
  const copy = GATE_REASON_COPY[code];
  return copy ? { ...copy, known: true } : { ...UNKNOWN_GATE_REASON };
}
