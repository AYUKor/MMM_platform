import { useQuery } from "@tanstack/react-query";
import {
  getActiveModelPassport,
  ModelPassportUnavailableError,
  UnsupportedModelPassportContractError,
} from "../shared/api/model-passport-client";
import { Card } from "../shared/ui/Card";
import { PageHeader } from "../shared/ui/PageHeader";
import { StatusBadge } from "../shared/ui/StatusBadge";
import { ModelPassport } from "../widgets/model-passport/ModelPassport";
import styles from "../widgets/model-passport/model-passport.module.css";

function PassportLoading() {
  return (
    <div className={styles.statePage}>
      <PageHeader
        eyebrow={<span>Model Passport</span>}
        title="Паспорт модели"
        meta={<span>Запрашиваем активную модель</span>}
        actions={<StatusBadge>Загрузка</StatusBadge>}
      />
      <div className={styles.loadingGrid} role="status" aria-live="polite">
        <span className="sr-only">Загрузка паспорта модели</span>
        <div className={styles.loadingBlock} />
        <div className={styles.loadingBlock} />
        <div className={styles.loadingBlock} />
      </div>
    </div>
  );
}

function PassportState({
  code,
  title,
  description,
  tone,
  onRetry,
}: {
  code: string;
  title: string;
  description: string;
  tone: "neutral" | "warning" | "danger";
  onRetry: () => void;
}) {
  return (
    <div className={styles.statePage}>
      <PageHeader
        eyebrow={<span>Model Passport</span>}
        title="Паспорт модели"
        meta={<span>Источник — только сервис моделей</span>}
        actions={<StatusBadge tone={tone}>{code}</StatusBadge>}
      />
      <Card
        as="section"
        className={styles.stateCard}
        role={tone === "danger" ? "alert" : "status"}
      >
        <span className={styles.stateCode}>{code}</span>
        <h2>{title}</h2>
        <p>{description}</p>
        <button type="button" className={styles.retryButton} onClick={onRetry}>
          Повторить запрос
        </button>
      </Card>
    </div>
  );
}

export function ModelPassportPage() {
  const query = useQuery({
    queryKey: ["model-passport", "active"],
    queryFn: () => getActiveModelPassport(),
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  if (query.isPending) return <PassportLoading />;

  if (query.error instanceof ModelPassportUnavailableError) {
    return (
      <PassportState
        code="Нет данных"
        title="Паспорт модели временно недоступен"
        description="Сервис моделей пока не может вернуть проверенный паспорт активной модели. Интерфейс не подставляет значения из внутренних хранилищ, документации или локальных файлов."
        tone="warning"
        onRetry={() => { void query.refetch(); }}
      />
    );
  }

  if (query.error instanceof UnsupportedModelPassportContractError) {
    return (
      <PassportState
        code="Версия API"
        title="Контракт паспорта не поддерживается"
        description="Сервис не поддерживает этот запрос или ответ не прошёл строгую проверку ModelPassport v1. Неизвестные поля и значения не показываются."
        tone="warning"
        onRetry={() => { void query.refetch(); }}
      />
    );
  }

  if (query.isError || !query.data) {
    return (
      <PassportState
        code="Ошибка"
        title="Не удалось загрузить паспорт модели"
        description="Соединение с сервисом моделей прервалось или сервис вернул ошибку. Повторите запрос после восстановления доступа."
        tone="danger"
        onRetry={() => { void query.refetch(); }}
      />
    );
  }

  return <ModelPassport passport={query.data} />;
}
