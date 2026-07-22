import { describe, expect, it } from "vitest";
import { AuthAdminError } from "../../shared/api/auth-admin-client";
import { bootstrapErrorCopy, loginErrorCopy, registrationErrorCopy } from "./authModel";

function unsupportedContractError() {
  return new AuthAdminError("Сервис вернул неподдерживаемый формат данных.", {
    status: 200,
    code: "UNSUPPORTED_AUTH_ADMIN_CONTRACT",
    retryable: false,
    userAction: "Обновите приложение.",
  });
}

describe("loginErrorCopy", () => {
  it("uses identical generic copy for every invalid-credentials 401", () => {
    const unknownEmail = loginErrorCopy({
      status: 401,
      displayText: "Пользователь с таким email не найден.",
    });
    const wrongPassword = loginErrorCopy({
      status: 401,
      displayText: "Пароль не совпал.",
    });

    expect(unknownEmail).toEqual(wrongPassword);
    expect(unknownEmail).toEqual({
      title: "Не удалось войти",
      description: "Проверьте email и пароль локальной pilot-учетной записи.",
    });
  });

  it("shows controlled rate-limit copy for 429", () => {
    expect(loginErrorCopy({ status: 429 })).toEqual({
      title: "Слишком много попыток",
      description: "Вход временно ограничен. Подождите и повторите попытку.",
    });
    expect(loginErrorCopy({
      status: 429,
      displayText: "Повторите попытку через несколько минут.",
    })).toEqual({
      title: "Слишком много попыток",
      description: "Повторите попытку через несколько минут.",
    });
  });
});

describe("registrationErrorCopy", () => {
  it("shows the server validation message for 422", () => {
    expect(registrationErrorCopy({
      status: 422,
      displayText: "Пароль должен содержать от 12 до 256 символов.",
    })).toEqual({
      title: "Проверьте данные регистрации",
      description: "Пароль должен содержать от 12 до 256 символов.",
    });
    expect(registrationErrorCopy({ status: 422 })).toEqual({
      title: "Проверьте данные регистрации",
      description: "Email, пароль или имя заполнены некорректно.",
    });
  });

  it("keeps the duplicate-email 409 non-confirming", () => {
    expect(registrationErrorCopy({
      status: 409,
      displayText: "Не удалось создать учетную запись. Возможно, такой адрес уже зарегистрирован — попробуйте войти в систему.",
    })).toEqual({
      title: "Не удалось создать учетную запись",
      description: "Не удалось создать учетную запись. Возможно, такой адрес уже зарегистрирован — попробуйте войти в систему.",
    });
    expect(registrationErrorCopy({ status: 409 })).toEqual({
      title: "Не удалось создать учетную запись",
      description: "Возможно, такой адрес уже зарегистрирован — попробуйте войти в систему.",
    });
  });

  it("shows controlled rate-limit and fallback copy", () => {
    expect(registrationErrorCopy({ status: 429 })).toEqual({
      title: "Слишком много попыток",
      description: "Регистрация временно ограничена. Подождите и повторите попытку.",
    });
    expect(registrationErrorCopy(new Error("network")).title)
      .toBe("Сервис регистрации недоступен");
    expect(registrationErrorCopy(unsupportedContractError()).title)
      .toBe("Версия регистрации не поддерживается");
  });
});

describe("bootstrapErrorCopy", () => {
  it("separates the real unsupported-contract error from temporary session errors", () => {
    expect(bootstrapErrorCopy(unsupportedContractError()).title)
      .toBe("Версия входа не поддерживается");
    expect(loginErrorCopy(unsupportedContractError()).title)
      .toBe("Версия входа не поддерживается");
    expect(bootstrapErrorCopy(new Error("network")).title)
      .toBe("Не удалось проверить сессию");
  });
});
