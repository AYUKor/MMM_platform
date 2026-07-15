import { describe, expect, it } from "vitest";
import { routes } from "./router";

describe("router", () => {
  it("contains the Phase 1 result route and permission-aware admin placeholders", () => {
    const root = routes.find((route) => route.path === "/");
    const childPaths = root?.children?.map((route) => route.path).filter(Boolean);
    expect(childPaths).toContain("calculations/:id/result");
    expect(childPaths).toContain("calculations/:id/progress");
    expect(childPaths).toContain("calculations/new");
    expect(childPaths).toContain("admin/system");
    expect(childPaths).toContain("admin/jobs");
  });
});
