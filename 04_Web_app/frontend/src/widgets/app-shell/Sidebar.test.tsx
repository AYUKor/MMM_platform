import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Sidebar } from "./Sidebar";

function renderSidebar(pathname: string) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("Sidebar active navigation", () => {
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
});
