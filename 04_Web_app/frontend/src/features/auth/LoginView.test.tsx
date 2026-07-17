import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../shared/theme/ThemeProvider";
import { LoginView } from "./LoginView";

function renderLogin(onSubmit: (email: string, password: string) => Promise<void>) {
  return render(
    <ThemeProvider>
      <LoginView notice={null} onSubmit={onSubmit} />
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
});
