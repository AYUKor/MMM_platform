export interface AuthErrorCopy {
  title: string;
  description: string;
}

function statusOf(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("status" in error)) return null;
  const status = (error as { status?: unknown }).status;
  return typeof status === "number" ? status : null;
}

function displayTextOf(error: unknown): string | null {
  if (!error || typeof error !== "object") return null;
  const value = (error as { displayText?: unknown }).displayText;
  if (typeof value === "string" && value.trim()) return value;
  return error instanceof Error && error.name === "AuthAdminError" && error.message.trim()
    ? error.message
    : null;
}

function isUnsupportedContract(error: unknown): boolean {
  return Boolean(error && typeof error === "object" &&
    (error as { code?: unknown }).code === "UNSUPPORTED_AUTH_ADMIN_CONTRACT");
}

export function loginErrorCopy(error: unknown): AuthErrorCopy {
  if (isUnsupportedContract(error)) {
    return {
      title: "Версия входа не поддерживается",
      description: "Сервис вернул неподдерживаемый формат сессии. Обновите приложение или обратитесь к администратору.",
    };
  }
  const status = statusOf(error);
  if (status === 401) {
    return {
      title: "Не удалось войти",
      description: "Проверьте email и пароль локальной pilot-учетной записи.",
    };
  }
  if (status === 429) {
    return {
      title: "Слишком много попыток",
      description: displayTextOf(error) ?? "Вход временно ограничен. Подождите и повторите попытку.",
    };
  }
  if (status === 403) {
    return {
      title: "Вход отклонен",
      description: "Не удалось подтвердить безопасный запрос. Обновите страницу и повторите попытку.",
    };
  }
  return {
    title: "Сервис входа недоступен",
    description: displayTextOf(error) ?? "Не удалось связаться с сервисом. Повторите попытку позже.",
  };
}

export function bootstrapErrorCopy(error: unknown): AuthErrorCopy {
  return isUnsupportedContract(error)
    ? {
        title: "Версия входа не поддерживается",
        description: "Сервис вернул неподдерживаемый формат сессии. Обновите приложение или обратитесь к администратору.",
      }
    : {
        title: "Не удалось проверить сессию",
        description: "Проверьте подключение к сервису и повторите попытку.",
      };
}
