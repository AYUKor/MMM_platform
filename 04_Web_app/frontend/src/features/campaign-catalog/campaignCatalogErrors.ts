export interface CampaignCatalogErrorCopy {
  title: string;
  description: string;
  retryable: boolean;
}

export function campaignCatalogErrorCopy(error: unknown): CampaignCatalogErrorCopy {
  const name = error instanceof Error ? error.name : "";
  if (name === "CampaignNotFoundError") {
    return {
      title: "Кампания не найдена",
      description: "Кампании с таким номером нет в каталоге активной модели. Откройте список и выберите кампанию из него.",
      retryable: false,
    };
  }
  if (name === "CampaignCatalogNotPublishedError") {
    return {
      title: "Каталог пока не опубликован",
      description: "Каталог прошлых кампаний для активной модели появится после публикации.",
      retryable: false,
    };
  }
  if (name === "UnsupportedCampaignCatalogContractError") {
    return {
      title: "Формат каталога не поддерживается",
      description: "Ответ не прошёл защитную проверку и поэтому не показан.",
      retryable: true,
    };
  }
  if (name === "CampaignCatalogUnavailableError") {
    return {
      title: "Каталог временно недоступен",
      description: "Файлы каталога не прошли проверку привязки к модели или сервис занят. Повторите позже или сообщите ответственному за инструмент.",
      retryable: true,
    };
  }
  return {
    title: "Не удалось загрузить каталог",
    description: "Проверьте соединение и повторите запрос.",
    retryable: true,
  };
}
