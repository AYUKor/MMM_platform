import { describe, expect, it } from "vitest";
import { AuthAdminError } from "../../shared/api/auth-admin-client";
import { bootstrapErrorCopy, loginErrorCopy } from "./authModel";

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
