import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../shared/theme/ThemeProvider";
import { Topbar } from "./Topbar";

const authMock = vi.hoisted(() => ({
  permissions: [] as string[],
  logout: vi.fn().mockResolvedValue(undefined),
  session: {
    user: {
      display_name: "Мария Аналитик",
      email: "maria@example.org",
      role: { title: "Аналитик" },
    },
  },
}));

vi.mock("../../features/auth/AuthProvider", () => ({
  useAuth: () => ({
    session: authMock.session,
    canAny: (permissions: string[]) => permissions.some((permission) =>
      authMock.permissions.includes(permission)),
    logout: authMock.logout,
  }),
}));

function renderTopbar() {
  return render(
    <MemoryRouter>
      <ThemeProvider><Topbar /></ThemeProvider>
    </MemoryRouter>,
  );
}

describe("Topbar profile", () => {
  beforeEach(() => {
    authMock.permissions = [];
    authMock.logout.mockClear();
  });

  it("shows browser-safe profile details without raw permission IDs", () => {
    renderTopbar();
    fireEvent.click(screen.getByRole("button", { name: /Мария Аналитик/ }));

    expect(screen.getAllByText("Мария Аналитик").length).toBeGreaterThan(0);
    expect(screen.getByText("Аналитик")).toBeInTheDocument();
    expect(screen.getByText("maria@example.org")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Выйти" })).toBeInTheDocument();
    expect(screen.queryByText("admin.users.read")).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Администрирование" })).not.toBeInTheDocument();
  });

  it("shows the admin entry only when an admin read permission exists", () => {
    authMock.permissions = ["admin.audit.read"];
    renderTopbar();
    fireEvent.click(screen.getByRole("button", { name: /Мария Аналитик/ }));

    expect(screen.getByRole("menuitem", { name: "Администрирование" }))
      .toHaveAttribute("href", "/admin");
  });
});
