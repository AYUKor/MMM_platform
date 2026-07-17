import { isValidElement } from "react";
import { describe, expect, it } from "vitest";
import { routes } from "./router";

function childRoute(path: string) {
  const root = routes.find((route) => route.path === "/");
  return root?.children?.find((route) => route.path === path);
}

function routePermission(path: string): string | null {
  const element = childRoute(path)?.element;
  if (!isValidElement<{ permission?: unknown }>(element)) return null;
  return typeof element.props.permission === "string"
    ? element.props.permission
    : null;
}

describe("router", () => {
  it("keeps login public and all product routes under the protected root", () => {
    const root = routes.find((route) => route.path === "/");
    const childPaths = root?.children?.map((route) => route.path).filter(Boolean);
    expect(routes.find((route) => route.path === "/login")?.element).toBeTruthy();
    expect(root?.element).toBeTruthy();
    expect(root?.children?.some((route) => route.index)).toBe(true);
    expect(childPaths).toContain("calculations");
    expect(childPaths).toContain("calculations/:id/result");
    expect(childPaths).toContain("calculations/:id/progress");
    expect(childPaths).toContain("calculations/new");
    expect(childPaths).toContain("model");
    expect(childPaths).toContain("help");
  });

  it("contains the Phase E administration routes and no legacy placeholders", () => {
    const root = routes.find((route) => route.path === "/");
    const childPaths = root?.children?.map((route) => route.path).filter(Boolean);

    expect(childPaths).toContain("admin");
    expect(childPaths).toContain("admin/users");
    expect(childPaths).toContain("admin/roles");
    expect(childPaths).toContain("admin/system");
    expect(childPaths).toContain("admin/audit");
    expect(childPaths).not.toContain("admin/jobs");
    expect(childPaths).not.toContain("admin/models");
    expect(childPaths).not.toContain("admin/errors");
  });

  it("declares route access from explicit permissions", () => {
    expect(routePermission("calculations/new")).toBe("calculation.create");
    expect(routePermission("calculations/:id/result")).toBe("result.read");
    expect(routePermission("admin/users")).toBe("admin.users.read");
    expect(routePermission("admin/roles")).toBe("admin.users.read");
    expect(routePermission("admin/system")).toBe("admin.system.read");
    expect(routePermission("admin/audit")).toBe("admin.audit.read");
  });
});
