import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "./Sidebar";

const authMock = vi.hoisted(() => ({
  permissions: [] as string[],
  session: null as null | {
    user: {
      display_name: string;
      email: string;
      role: { title: string };
    };
  },
}));

vi.mock("../../features/auth/AuthProvider", () => ({
  useAuth: () => ({
    session: authMock.session,
    can: (permission: string) => authMock.permissions.includes(permission),
    canAny: (permissions: string[]) => permissions.some((permission) =>
      authMock.permissions.includes(permission)),
  }),
}));

const PRIMARY_PERMISSIONS = [
  "workspace.read",
  "calculation.create",
  "calculation.read",
  "model.read",
  "help.read",
] as const;

function renderSidebar(pathname: string) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("Sidebar active navigation", () => {
  beforeEach(() => {
    authMock.permissions = [...PRIMARY_PERMISSIONS];
    authMock.session = {
      user: {
        display_name: "Мария Аналитик",
        email: "maria@example.org",
        role: { title: "Аналитик" },
      },
    };
  });

  it("marks only New Calculation on the new calculation flow", () => {
    renderSidebar("/calculations/new?step=scenarios");

    expect(screen.getByRole("link", { name: "Новый расчёт" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "История расчетов" })).not.toHaveAttribute("aria-current");
  });

  it("keeps My Calculations active on nested progress and result pages", () => {
    renderSidebar("/calculations/job_000000000001/result");

    expect(screen.getByRole("link", { name: "История расчетов" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Новый расчёт" })).not.toHaveAttribute("aria-current");
  });

  it("marks Home and Help only on their exact product routes", () => {
    const { unmount } = renderSidebar("/");
    expect(screen.getByRole("link", { name: "Главная" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "История расчетов" })).not.toHaveAttribute("aria-current");
    unmount();

    renderSidebar("/help?section=scenarios&article=scenario_s5");
    expect(screen.getByRole("link", { name: "Справка" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Главная" })).not.toHaveAttribute("aria-current");
  });

  it("builds product and admin navigation only from returned permissions", () => {
    authMock.permissions = ["workspace.read", "admin.system.read"];
    renderSidebar("/admin/system");

    expect(screen.getByRole("link", { name: "Главная" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Новый расчёт" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Система" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: "Пользователи" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Роли" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Журнал действий" })).not.toBeInTheDocument();
  });

  it("does not infer admin navigation from the displayed role", () => {
    authMock.permissions = [...PRIMARY_PERMISSIONS];
    authMock.session = {
      user: {
        display_name: "Администратор без permission",
        email: "admin@example.org",
        role: { title: "Администратор" },
      },
    };
    renderSidebar("/");

    expect(screen.queryByText("Администрирование")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Пользователи" })).not.toBeInTheDocument();
    expect(screen.getByText("Администратор без permission")).toBeInTheDocument();
    expect(screen.getByText("Администратор")).toBeInTheDocument();
    expect(screen.queryByText("admin.users.read")).not.toBeInTheDocument();
  });

  it("shows users and roles together for admin.users.read", () => {
    authMock.permissions = ["admin.users.read"];
    renderSidebar("/admin/roles");

    expect(screen.getByRole("link", { name: "Пользователи" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Роли" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: "Система" })).not.toBeInTheDocument();
  });
});
