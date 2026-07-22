import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../shared/theme/ThemeProvider";
import { LoginView } from "./LoginView";

function renderLogin(
  onSubmit: (email: string, password: string) => Promise<void>,
  onRegister?: (email: string, password: string, displayName: string | null) => Promise<void>,
) {
  return render(
    <ThemeProvider>
      <LoginView notice={null} onSubmit={onSubmit} onRegister={onRegister} />
    </ThemeProvider>,
  );
}

function fillCredentials(email = "user@example.org", password = "Pilot-password-2026") {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: password } });
}

describe("LoginView", () => {
  it("clears only the password and focuses generic feedback after a 401", async () => {
    const onSubmit = vi.fn().mockRejectedValue({
      status: 401,
      displayText: "RAW_ACCOUNT_DETAIL",
    });
    renderLogin(onSubmit);
    fillCredentials();

    fireEvent.submit(screen.getByRole("button", { name: "Войти" }).closest("form")!);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Не удалось войти");
    expect(alert).not.toHaveTextContent("RAW_ACCOUNT_DETAIL");
    expect(screen.getByLabelText("Пароль")).toHaveValue("");
    expect(screen.getByLabelText("Email")).toHaveValue("user@example.org");
    await waitFor(() => expect(alert).toHaveFocus());
  });

  it("keeps native form semantics for keyboard submit", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderLogin(onSubmit);
    fillCredentials("  analyst@example.org  ", "Pilot-password-2026");
    const submitButton = screen.getByRole("button", { name: "Войти" });
    const password = screen.getByLabelText("Пароль");

    expect(submitButton).toHaveAttribute("type", "submit");
    password.focus();
    fireEvent.keyDown(password, { key: "Enter", code: "Enter" });
    fireEvent.submit(submitButton.closest("form")!);

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(
      "analyst@example.org",
      "Pilot-password-2026",
    ));
  });

  it("disables duplicate submit while login is pending", async () => {
    let resolveLogin: (() => void) | undefined;
    const onSubmit = vi.fn(() => new Promise<void>((resolve) => {
      resolveLogin = resolve;
    }));
    renderLogin(onSubmit);
    fillCredentials();
    const form = screen.getByRole("button", { name: "Войти" }).closest("form")!;

    fireEvent.submit(form);
    expect(await screen.findByRole("button", { name: "Входим…" })).toBeDisabled();
    fireEvent.submit(form);
    expect(onSubmit).toHaveBeenCalledTimes(1);

    resolveLogin?.();
    await waitFor(() => expect(screen.getByRole("button", { name: "Войти" })).toBeEnabled());
  });

  it("switches to the registration form and validates password confirmation locally", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onRegister = vi.fn().mockResolvedValue(undefined);
    renderLogin(onSubmit, onRegister);

    fireEvent.click(screen.getByRole("button", { name: "Создать учетную запись" }));
    fillCredentials("new-user@example.org", "New-password-2026");
    fireEvent.change(screen.getByLabelText("Повторите пароль"), {
      target: { value: "Other-password-2026" },
    });

    fireEvent.submit(screen.getByRole("button", { name: "Зарегистрироваться" }).closest("form")!);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Пароли не совпадают.");
    expect(onRegister).not.toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("registers with trimmed email and optional display name, then signs in", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onRegister = vi.fn().mockResolvedValue(undefined);
    renderLogin(onSubmit, onRegister);

    fireEvent.click(screen.getByRole("button", { name: "Создать учетную запись" }));
    fireEvent.change(screen.getByLabelText("Имя (необязательно)"), {
      target: { value: "  Новый аналитик  " },
    });
    fillCredentials("  new-user@example.org  ", "New-password-2026");
    fireEvent.change(screen.getByLabelText("Повторите пароль"), {
      target: { value: "New-password-2026" },
    });

    fireEvent.submit(screen.getByRole("button", { name: "Зарегистрироваться" }).closest("form")!);

    await waitFor(() => expect(onRegister).toHaveBeenCalledWith(
      "new-user@example.org",
      "New-password-2026",
      "Новый аналитик",
    ));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("omits a blank display name and shows the non-confirming duplicate copy", async () => {
    const onRegister = vi.fn().mockRejectedValue({
      status: 409,
      displayText: "Не удалось создать учетную запись. Возможно, такой адрес уже зарегистрирован — попробуйте войти в систему.",
    });
    renderLogin(vi.fn().mockResolvedValue(undefined), onRegister);

    fireEvent.click(screen.getByRole("button", { name: "Создать учетную запись" }));
    fillCredentials("existing@example.org", "Existing-password-2026");
    fireEvent.change(screen.getByLabelText("Повторите пароль"), {
      target: { value: "Existing-password-2026" },
    });

    fireEvent.submit(screen.getByRole("button", { name: "Зарегистрироваться" }).closest("form")!);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Возможно, такой адрес уже зарегистрирован");
    expect(alert).not.toHaveTextContent("existing@example.org");
    await waitFor(() => expect(onRegister).toHaveBeenCalledWith(
      "existing@example.org",
      "Existing-password-2026",
      null,
    ));
    expect(screen.getByLabelText("Пароль")).toHaveValue("");
  });
});
