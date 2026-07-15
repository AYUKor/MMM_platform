import type {
  ModelPassportAllowedUse,
  ModelPassportEvidenceStatus,
  ModelPassportV1,
} from "../../entities/model-passport/types";

export type PassportTone = "neutral" | "accent" | "warning" | "danger";

export interface PassportCopy {
  label: string;
  description: string;
  tone: PassportTone;
}

const allowedUseCopy: Record<ModelPassportAllowedUse, PassportCopy> = {
  primary: {
    label: "Основное применение",
    description: "Показатель можно использовать для прогноза и разрешенной оптимизации.",
    tone: "accent",
  },
  caution: {
    label: "С осторожностью",
    description: "Прогноз доступен, но автоматическое увеличение бюджета ограничено.",
    tone: "warning",
  },
  diagnostic: {
    label: "Только диагностика",
    description: "Показатель не может управлять оптимизацией или получать дополнительный бюджет.",
    tone: "neutral",
  },
  unavailable: {
    label: "Недоступно",
    description: "Автоматический прогноз или оптимизация для этой комбинации недоступны.",
    tone: "danger",
  },
};

const evidenceCopy: Record<ModelPassportEvidenceStatus, PassportCopy> = {
  passed: {
    label: "Пройдено",
    description: "Проверка завершена и прошла заявленные критерии.",
    tone: "accent",
  },
  unavailable: {
    label: "Нет данных",
    description: "Подтверждающие данные для этой проверки пока отсутствуют.",
    tone: "warning",
  },
  failed: {
    label: "Не пройдено",
    description: "Проверка выполнена, но обязательные критерии не пройдены.",
    tone: "danger",
  },
};

const targetLabels: Readonly<Record<string, string>> = {
  turnover_per_user: "Оборот на пользователя",
  orders_per_user: "Заказы на пользователя",
  avg_basket: "Средний чек",
};

export function getAllowedUseCopy(code: ModelPassportAllowedUse): PassportCopy {
  return allowedUseCopy[code];
}

export function getEvidenceCopy(status: ModelPassportEvidenceStatus): PassportCopy {
  return evidenceCopy[status];
}

export function getTargetLabel(target: string, fallbackOrdinal?: number): string {
  return targetLabels[target] ?? (
    fallbackOrdinal === undefined
      ? "Показатель без пользовательского названия"
      : `Показатель ${fallbackOrdinal} — название не поддерживается`
  );
}

export function getDeploymentProfileCopy(
  profile: ModelPassportV1["serving"]["deployment_profile"],
): PassportCopy {
  if (profile === "research_pilot") {
    return {
      label: "Исследовательский pilot",
      description: "Среда предназначена для исследовательских расчетов и проверки продукта.",
      tone: "warning",
    };
  }
  return {
    label: "Локальная исследовательская среда",
    description: "Сервис работает в локальном development-профиле.",
    tone: "neutral",
  };
}

export function getCalculationCopy(calculationAllowed: boolean): PassportCopy {
  return calculationAllowed
    ? {
        label: "Research-расчеты доступны",
        description: "По данным паспорта доступны forecast и распределение бюджета в research-контуре.",
        tone: "accent",
      }
    : {
        label: "Расчеты недоступны",
        description: "Текущий пакет не разрешает запуск research-расчетов.",
        tone: "danger",
      };
}

export function getRecordOriginCopy(
  origin: ModelPassportV1["record_origin"],
): PassportCopy {
  return origin === "synthetic_fixture"
    ? {
        label: "Демонстрационные данные",
        description: "Паспорт получен из явно синтетического API-ответа и не является production evidence.",
        tone: "warning",
      }
    : {
        label: "Проверенный пакет",
        description: "Паспорт построен backend из проверенного model package.",
        tone: "accent",
      };
}
