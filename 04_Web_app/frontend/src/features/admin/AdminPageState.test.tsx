import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AuthAdminError } from "../../shared/api/auth-admin-client";
import { AdminError } from "./AdminPageState";

describe("AdminError", () => {
  it("renders the real unsupported-contract state by error code", () => {
    const error = new AuthAdminError("Сервис вернул неподдерживаемый формат данных.", {
      status: 200,
      code: "UNSUPPORTED_AUTH_ADMIN_CONTRACT",
      retryable: false,
      userAction: "Обновите приложение.",
    });

    render(<AdminError error={error} onRetry={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Формат ответа не поддерживается" }))
      .toBeInTheDocument();
    expect(screen.getByText("Сервис вернул неподдерживаемый формат данных."))
      .toBeInTheDocument();
  });

  it("keeps a 403 distinct from an expired session", () => {
    const error = new AuthAdminError("Недостаточно прав.", {
      status: 403,
      code: "PERMISSION_DENIED",
      retryable: false,
      userAction: "Обратитесь к администратору.",
    });

    render(<AdminError error={error} onRetry={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Недостаточно прав" }))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Повторить" })).not.toBeInTheDocument();
  });
});
