import { describe, expect, it } from "vitest";
import { routes } from "./router";

describe("router", () => {
  it("contains the Phase D product-navigation and calculation routes", () => {
    const root = routes.find((route) => route.path === "/");
    const childPaths = root?.children?.map((route) => route.path).filter(Boolean);
    expect(root?.children?.some((route) => route.index)).toBe(true);
    expect(childPaths).toContain("calculations");
    expect(childPaths).toContain("calculations/:id/result");
    expect(childPaths).toContain("calculations/:id/progress");
    expect(childPaths).toContain("calculations/new");
    expect(childPaths).toContain("model");
    expect(childPaths).toContain("help");
    expect(childPaths).toContain("admin/system");
    expect(childPaths).toContain("admin/jobs");
  });
});
