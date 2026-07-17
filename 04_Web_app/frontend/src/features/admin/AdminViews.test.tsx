import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createAdminAuditLogFixture,
  createAdminRoleCatalogFixture,
  createAdminSystemStatusFixture,
  createAdminUserDetailFixture,
  createAdminUserListFixture,
} from "../../test/authAdminFixtures";
import {
  createAdminUser,
  getAdminAudit,
  getAdminRoles,
  getAdminSystemStatus,
  getAdminUsers,
  patchAdminUser,
  revokeAdminUserSessions,
  setAdminUserEnabled,
} from "../../shared/api/auth-admin-client";
import { useAuth } from "../auth/AuthProvider";
import { AdminAuditView } from "./AdminAuditView";
import { AdminRolesView } from "./AdminRolesView";
import { AdminSystemStatusView } from "./AdminSystemStatusView";
import { AdminUsersView } from "./AdminUsersView";

vi.mock("../../shared/api/auth-admin-client", () => ({
  createAdminUser: vi.fn(),
  getAdminAudit: vi.fn(),
  getAdminRoles: vi.fn(),
  getAdminSystemStatus: vi.fn(),
  getAdminUsers: vi.fn(),
  patchAdminUser: vi.fn(),
  revokeAdminUserSessions: vi.fn(),
  setAdminUserEnabled: vi.fn(),
}));

vi.mock("../auth/AuthProvider", () => ({ useAuth: vi.fn() }));

function renderAdminView(node: React.ReactNode, path = "/admin") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

function authWith(permissions: string[]) {
  vi.mocked(useAuth).mockReturnValue({
    can: (permission: string) => permissions.includes(permission),
  } as ReturnType<typeof useAuth>);
}

beforeEach(() => {
  vi.clearAllMocks();
  authWith([]);
  vi.mocked(getAdminUsers).mockResolvedValue(createAdminUserListFixture());
  vi.mocked(getAdminRoles).mockResolvedValue(createAdminRoleCatalogFixture());
  vi.mocked(getAdminSystemStatus).mockResolvedValue(createAdminSystemStatusFixture());
  vi.mocked(getAdminAudit).mockResolvedValue(createAdminAuditLogFixture());
  vi.mocked(patchAdminUser).mockResolvedValue(createAdminUserDetailFixture());
  vi.mocked(setAdminUserEnabled).mockResolvedValue(createAdminUserDetailFixture());
  vi.mocked(revokeAdminUserSessions).mockResolvedValue({
    user_id: "usr_333333333333333333333333",
    revoked_sessions_n: 1,
  });
});

describe("Phase E admin read views", () => {
  it("renders the published Roles catalog as titles and descriptions, not raw IDs", async () => {
    const catalog = createAdminRoleCatalogFixture();
    const { container } = renderAdminView(<AdminRolesView />, "/admin/roles");

    expect(await screen.findByRole("heading", { name: "Наблюдатель" })).toBeInTheDocument();
    expect(screen.getByText("Просмотр пользователей")).toBeInTheDocument();
    expect(screen.getByText(catalog.roles[2].description)).toBeInTheDocument();
    expect(screen.getByText(catalog.catalog_version)).toBeInTheDocument();
    expect(container).not.toHaveTextContent("admin.users.read");
    expect(container).not.toHaveTextContent("admin.roles.write");
  });

  it("renders reconciled System status and hides the source revision", async () => {
    const status = createAdminSystemStatusFixture();
    const { container } = renderAdminView(<AdminSystemStatusView />, "/admin/system");

    expect(await screen.findByRole("heading", { name: "Есть ограничения" }))
      .toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Активная модель" })).toBeInTheDocument();
    expect(screen.getAllByText("Есть ограничения").length).toBeGreaterThan(1);
    expect(screen.getByText("Расчеты разрешены").nextElementSibling).toHaveTextContent("Нет");
    expect(container).not.toHaveTextContent(status.build.source_revision ?? "missing-revision");
  });

  it("renders browser-safe Audit labels while hiding request and user IDs", async () => {
    const audit = createAdminAuditLogFixture();
    const { container } = renderAdminView(<AdminAuditView />, "/admin/audit");

    expect(await screen.findAllByText("Активные сеансы пользователя завершены."))
      .not.toHaveLength(0);
    expect(screen.getAllByText("Сессии завершены").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Выполнено").length).toBeGreaterThan(0);
    for (const event of audit.items) {
      expect(container).not.toHaveTextContent(event.request_id);
      if (event.actor_user_id) expect(container).not.toHaveTextContent(event.actor_user_id);
      if (event.target_id) expect(container).not.toHaveTextContent(event.target_id);
    }
  });
});

describe("Phase E Users permission separation", () => {
  it("requires both users.write and roles.write before exposing user creation", async () => {
    authWith(["admin.users.write"]);
    const first = renderAdminView(<AdminUsersView />, "/admin/users");

    expect(await screen.findAllByText("Мария Соколова")).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Добавить пользователя" }))
      .not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Изменить" }).length).toBeGreaterThan(0);
    first.unmount();

    authWith(["admin.users.write", "admin.roles.write"]);
    renderAdminView(<AdminUsersView />, "/admin/users");

    const createButton = await screen.findByRole("button", { name: "Добавить пользователя" });
    await waitFor(() => expect(createButton).toBeEnabled());
    fireEvent.click(createButton);
    expect(screen.getByRole("dialog", { name: "Новый пользователь" })).toBeInTheDocument();
    expect(createAdminUser).not.toHaveBeenCalled();
  });

  it("exposes session revoke only with sessions.write and calls the dedicated mutation", async () => {
    authWith(["admin.sessions.write"]);
    renderAdminView(<AdminUsersView />, "/admin/users");

    expect(await screen.findAllByText("Мария Соколова")).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Добавить пользователя" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Изменить" })).not.toBeInTheDocument();

    const revokeButtons = screen.getAllByRole("button", { name: "Завершить сессии" });
    const enabledRevoke = revokeButtons.find((button) => !button.hasAttribute("disabled"));
    expect(enabledRevoke).toBeDefined();
    fireEvent.click(enabledRevoke as HTMLButtonElement);
    expect(screen.getByRole("dialog", { name: "Завершить активные сессии?" }))
      .toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));

    await waitFor(() => {
      expect(revokeAdminUserSessions).toHaveBeenCalledWith(
        "usr_333333333333333333333333",
      );
    });
    expect(patchAdminUser).not.toHaveBeenCalled();
    expect(setAdminUserEnabled).not.toHaveBeenCalled();
  });

  it("allows users.write to rename and change status without sending a role", async () => {
    authWith(["admin.users.write"]);
    renderAdminView(<AdminUsersView />, "/admin/users");

    const row = (await screen.findAllByRole("row"))
      .find((item) => item.textContent?.includes("Мария Соколова"));
    expect(row).toBeDefined();
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "Изменить" }));
    const dialog = screen.getByRole("dialog", { name: "Настройки пользователя" });
    const roleSelect = within(dialog).getByRole("combobox");
    expect(roleSelect).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Имя"), { target: { value: "Мария Новая" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(patchAdminUser).toHaveBeenCalledWith(
      "usr_111111111111111111111111",
      { display_name: "Мария Новая" },
    ));
    expect(vi.mocked(patchAdminUser).mock.calls[0][1]).not.toHaveProperty("role_id");

    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "Отключить" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Подтвердить" }));
    await waitFor(() => expect(setAdminUserEnabled).toHaveBeenCalledWith(
      "usr_111111111111111111111111",
      false,
    ));
  });

  it("sends only a changed role when both HTTP-required write permissions exist", async () => {
    authWith(["admin.users.write", "admin.roles.write"]);
    renderAdminView(<AdminUsersView />, "/admin/users");

    const row = (await screen.findAllByRole("row"))
      .find((item) => item.textContent?.includes("Мария Соколова"));
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "Изменить" }));
    const dialog = screen.getByRole("dialog", { name: "Настройки пользователя" });
    fireEvent.change(within(dialog).getByRole("combobox"), { target: { value: "viewer" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(patchAdminUser).toHaveBeenCalledWith(
      "usr_111111111111111111111111",
      { role_id: "viewer" },
    ));
    expect(vi.mocked(patchAdminUser).mock.calls[0][1]).not.toHaveProperty("display_name");
  });

  it("suppresses cached protected data after a later 403", async () => {
    const denied = Object.assign(new Error("Недостаточно прав."), {
      name: "AuthAdminError",
      status: 403,
      code: "PERMISSION_DENIED",
      retryable: false,
      userAction: "Обратитесь к администратору.",
    });
    vi.mocked(getAdminRoles)
      .mockResolvedValueOnce(createAdminRoleCatalogFixture())
      .mockRejectedValueOnce(denied);
    const { queryClient } = renderAdminView(<AdminRolesView />, "/admin/roles");

    expect(await screen.findByRole("heading", { name: "Наблюдатель" })).toBeInTheDocument();
    await queryClient.invalidateQueries({ queryKey: ["phase-e", "admin-roles"] });

    expect(await screen.findByRole("heading", { name: "Недостаточно прав" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Наблюдатель" })).not.toBeInTheDocument();
  });

  it("suppresses cached Users rows and write controls after a later 403", async () => {
    authWith(["admin.users.write", "admin.roles.write", "admin.sessions.write"]);
    const denied = Object.assign(new Error("Недостаточно прав."), {
      name: "AuthAdminError",
      status: 403,
      code: "PERMISSION_DENIED",
      retryable: false,
      userAction: "Обратитесь к администратору.",
    });
    vi.mocked(getAdminUsers)
      .mockResolvedValueOnce(createAdminUserListFixture())
      .mockRejectedValueOnce(denied);
    const { queryClient } = renderAdminView(<AdminUsersView />, "/admin/users");

    expect(await screen.findAllByText("Мария Соколова")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: "Добавить пользователя" })).toBeEnabled();
    await queryClient.invalidateQueries({ queryKey: ["phase-e", "admin-users"] });

    expect(await screen.findByRole("heading", { name: "Недостаточно прав" })).toBeInTheDocument();
    expect(screen.queryByText("Мария Соколова")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Добавить пользователя" }))
      .not.toBeInTheDocument();
  });
});
