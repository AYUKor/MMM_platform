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
    expect(screen.getByRole("link", { name: "Мои расчёты" })).not.toHaveAttribute("aria-current");
  });

  it("keeps My Calculations active on nested progress and result pages", () => {
    renderSidebar("/calculations/job_000000000001/result");

    expect(screen.getByRole("link", { name: "Мои расчёты" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Новый расчёт" })).not.toHaveAttribute("aria-current");
  });
});
