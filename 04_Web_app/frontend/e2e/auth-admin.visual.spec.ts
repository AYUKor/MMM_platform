import { expect, test, type Locator, type Page, type Route } from "@playwright/test";
import { fileURLToPath } from "node:url";
import {
  createAdminAuditLogFixture,
  createAdminRoleCatalogFixture,
  createAdminSystemStatusFixture,
  createAdminUserDetailFixture,
  createAdminUserListFixture,
  createAnonymousSessionFixture,
  createAuthenticatedSessionFixture,
} from "../src/test/authAdminFixtures";
import { createWorkspaceHomeFixture } from "../src/test/productNavigationFixtures";
import { measureContentContrast, type ContrastSample, type ContrastTarget } from "./support/contrast";

const REVIEW_DIRECTORY = fileURLToPath(
  new URL("../../docs/ui-review/phase-e-auth-admin-v1/", import.meta.url),
);

const PHASE_E_CONTRAST_TARGETS = [
  { name: "login guidance", selector: '[class*="loginForm"] > small' },
  { name: "filter labels", selector: '[class*="filterBar"] label > span, [class*="auditFilters"] label > span' },
  { name: "table headings", selector: '[class*="dataTable"] th' },
  { name: "table facts", selector: '[class*="dataTable"] td' },
  { name: "status pills", selector: '[class*="statusPill"]' },
  { name: "modal guidance", selector: '[class*="modalForm"] label small' },
  { name: "role permission descriptions", selector: '[class*="permissionList"] span' },
  { name: "system descriptions", selector: '[class*="systemCard"] > p' },
  { name: "system facts", selector: '[class*="systemCard"] dt' },
  { name: "system build labels", selector: '[class*="buildStrip"] span' },
  { name: "mobile user facts", selector: '[class*="userFacts"] dt' },
  { name: "mobile audit metadata", selector: '[class*="auditCard"] header' },
] as const satisfies readonly ContrastTarget[];

type RoleId = "viewer" | "analyst" | "admin";
type LoginMode = "success" | "invalid" | "rate-limited";

interface ApiOptions {
  authenticated?: boolean;
  theme?: "dark" | "light";
  role?: RoleId;
  loginMode?: LoginMode;
  usersUnauthorized?: boolean;
  systemForbidden?: boolean;
  mutationConflict?: boolean;
  emptyUsers?: boolean;
  emptyAudit?: boolean;
  systemUnavailable?: boolean;
  rolesUnavailable?: boolean;
  systemHttpUnavailable?: boolean;
  malformedAudit?: boolean;
  manyUsers?: boolean;
  manyAudit?: boolean;
  longAdminContent?: boolean;
}

interface ApiPageTrace {
  endpoint: "/api/v1/admin/users" | "/api/v1/admin/audit";
  requestedPage: number;
  requestedPageSize: number;
  payloadPage: number;
  firstVisibleText: string | null;
}

interface ApiTrace {
  pages: ApiPageTrace[];
}

function errorPayload(code: string, displayText: string, retryable: boolean) {
  return { error: { code, display_text: displayText, retryable, user_action: "Повторите попытку позже." } };
}

async function json(route: Route, payload: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
}

function manyUserItems() {
  const seed = createAdminUserListFixture().items;
  return Array.from({ length: 32 }, (_, index) => {
    const template = seed[index % seed.length];
    const timestamp = new Date(Date.UTC(2026, 6, 17, 12, 0) - index * 60_000).toISOString();
    return {
      ...template,
      user_id: `usr_${(index + 1).toString(16).padStart(24, "0")}`,
      display_name: index === 0
        ? "Александра-Екатерина Константинопольская с очень длинным отображаемым именем"
        : `Пользователь мобильной проверки ${String(index + 1).padStart(2, "0")}`,
      email: index === 0
        ? "alexandra-ekaterina.konstantinopolskaya.with-a-very-long-address@example.org"
        : `mobile.user.${String(index + 1).padStart(2, "0")}@example.org`,
      role: { ...template.role },
      created_at_utc: timestamp,
      updated_at_utc: timestamp,
      last_login_at_utc: timestamp,
      created_by_user_id: null,
      active_sessions_n: index % 4,
    };
  });
}

function usersPayload(url: URL, empty = false, many = false) {
  const value = structuredClone(createAdminUserListFixture());
  const page = Number(url.searchParams.get("page") ?? "1");
  const pageSize = Number(url.searchParams.get("page_size") ?? "25");
  const search = url.searchParams.get("search");
  const role = url.searchParams.get("role") as typeof value.applied_filters.role;
  const status = url.searchParams.get("status") as typeof value.applied_filters.status;
  const sort = (url.searchParams.get("sort") ?? "created_desc") as typeof value.applied_filters.sort;
  let items = empty ? [] : many ? manyUserItems() : [...value.items];
  if (search) items = items.filter((item) => `${item.display_name} ${item.email}`.toLocaleLowerCase("ru-RU").includes(search.toLocaleLowerCase("ru-RU")));
  if (role) items = items.filter((item) => item.role.role_id === role);
  if (status) items = items.filter((item) => item.status === status);
  items.sort((left, right) => sort === "name_asc"
    ? left.display_name.localeCompare(right.display_name, "ru")
    : sort === "email_asc"
      ? left.email.localeCompare(right.email)
      : sort === "created_asc"
        ? left.created_at_utc.localeCompare(right.created_at_utc)
        : sort === "last_login_desc"
          ? (right.last_login_at_utc ?? "").localeCompare(left.last_login_at_utc ?? "")
          : right.created_at_utc.localeCompare(left.created_at_utc));
  const totalItems = items.length;
  value.applied_filters = { search, role, status, sort };
  value.pagination = {
    page,
    page_size: pageSize,
    total_items: totalItems,
    total_pages: totalItems === 0 ? 0 : Math.ceil(totalItems / pageSize),
  };
  value.items = items.slice((page - 1) * pageSize, page * pageSize);
  return value;
}

function manyAuditItems() {
  const seed = createAdminAuditLogFixture().items;
  return Array.from({ length: 56 }, (_, index) => {
    const template = seed[index % seed.length];
    return {
      ...template,
      event_id: `evt_${(index + 1).toString(16).padStart(24, "0")}`,
      request_id: `req_${(index + 1).toString(16).padStart(24, "0")}`,
      occurred_at_utc: new Date(Date.UTC(2026, 6, 17, 13, 0) - index * 60_000).toISOString(),
      actor_display_name: index === 0
        ? "Александра-Екатерина Константинопольская — администратор длительной мобильной проверки"
        : template.actor_display_name,
      browser_safe_summary: index === 0
        ? "Проверено отображение длинного, но безопасного описания административного события на узком экране без выхода за границы карточки."
        : `${template.browser_safe_summary} Событие ${index + 1}.`,
    };
  });
}

function auditPayload(url: URL, empty = false, many = false) {
  const value = structuredClone(createAdminAuditLogFixture());
  const page = Number(url.searchParams.get("page") ?? "1");
  const pageSize = Number(url.searchParams.get("page_size") ?? "50");
  const actorUserId = url.searchParams.get("actor_user_id");
  const eventType = url.searchParams.get("event_type");
  const occurredFromUtc = url.searchParams.get("occurred_from_utc");
  const occurredToUtc = url.searchParams.get("occurred_to_utc");
  const sort = (url.searchParams.get("sort") ?? "occurred_desc") as typeof value.applied_filters.sort;
  let items = empty ? [] : many ? manyAuditItems() : [...value.items];
  if (actorUserId) items = items.filter((item) => item.actor_user_id === actorUserId);
  if (eventType) items = items.filter((item) => item.event_type === eventType);
  if (occurredFromUtc) items = items.filter((item) => item.occurred_at_utc >= occurredFromUtc);
  if (occurredToUtc) items = items.filter((item) => item.occurred_at_utc <= occurredToUtc);
  items.sort((left, right) => (sort === "occurred_desc" ? -1 : 1) * left.occurred_at_utc.localeCompare(right.occurred_at_utc));
  const totalItems = items.length;
  value.applied_filters = {
    actor_user_id: actorUserId,
    event_type: eventType,
    occurred_from_utc: occurredFromUtc,
    occurred_to_utc: occurredToUtc,
    sort,
  };
  value.pagination = {
    page,
    page_size: pageSize,
    total_items: totalItems,
    total_pages: totalItems === 0 ? 0 : Math.ceil(totalItems / pageSize),
  };
  value.items = items.slice((page - 1) * pageSize, page * pageSize);
  return value;
}

async function installApi(page: Page, options: ApiOptions = {}) {
  let authenticated = options.authenticated ?? true;
  const role = options.role ?? "admin";
  const loginMode = options.loginMode ?? "success";
  const trace: ApiTrace = { pages: [] };
  await page.addInitScript(({ theme }) => {
    localStorage.setItem("mmm-frontend-theme", theme);
    localStorage.setItem("mmm-review-data", "synthetic");
  }, { theme: options.theme ?? "dark" });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/auth/session" && request.method() === "GET") {
      await json(route, authenticated ? createAuthenticatedSessionFixture(role) : createAnonymousSessionFixture());
      return;
    }
    if (path === "/api/v1/auth/login" && request.method() === "POST") {
      if (loginMode === "invalid") {
        await json(route, errorPayload("AUTH_INVALID_CREDENTIALS", "Не удалось войти с указанными данными.", false), 401);
        return;
      }
      if (loginMode === "rate-limited") {
        await json(route, errorPayload("AUTH_RATE_LIMITED", "Вход временно ограничен.", true), 429);
        return;
      }
      authenticated = true;
      await json(route, createAuthenticatedSessionFixture(role));
      return;
    }
    if (path === "/api/v1/auth/logout" && request.method() === "POST") {
      authenticated = false;
      await json(route, createAnonymousSessionFixture());
      return;
    }
    if (path === "/api/v1/workspace/home") {
      await json(route, createWorkspaceHomeFixture());
      return;
    }
    if (path === "/api/v1/admin/users" && request.method() === "GET") {
      if (options.usersUnauthorized) {
        authenticated = false;
        await json(route, errorPayload("AUTH_SESSION_EXPIRED", "Сессия завершена.", false), 401);
        return;
      }
      const payload = usersPayload(url, options.emptyUsers, options.manyUsers);
      trace.pages.push({
        endpoint: path,
        requestedPage: Number(url.searchParams.get("page") ?? "1"),
        requestedPageSize: Number(url.searchParams.get("page_size") ?? "25"),
        payloadPage: payload.pagination.page,
        firstVisibleText: payload.items[0]?.display_name ?? null,
      });
      await json(route, payload);
      return;
    }
    if (path === "/api/v1/admin/users" && request.method() === "POST") {
      await json(route, createAdminUserDetailFixture(), 201);
      return;
    }
    if (/^\/api\/v1\/admin\/users\/usr_[0-9a-f]{24}(?:\/(?:enable|disable))?$/.test(path)) {
      if (options.mutationConflict && path.endsWith("/disable")) {
        await json(route, errorPayload("ADMIN_LAST_ADMIN_PROTECTED", "Нельзя отключить последнего активного администратора.", false), 409);
        return;
      }
      await json(route, createAdminUserDetailFixture());
      return;
    }
    if (/^\/api\/v1\/admin\/users\/usr_[0-9a-f]{24}\/sessions\/revoke$/.test(path)) {
      await json(route, { user_id: "usr_222222222222222222222222", revoked_sessions_n: 2 });
      return;
    }
    if (path === "/api/v1/admin/roles") {
      if (options.rolesUnavailable) {
        await json(route, errorPayload("ADMIN_ROLE_CATALOG_UNAVAILABLE", "Каталог ролей временно недоступен.", true), 503);
        return;
      }
      const value = createAdminRoleCatalogFixture();
      if (options.longAdminContent) {
        value.roles[0].description = "Наблюдатель может читать опубликованные рабочие сведения и результаты в пределах доступного пространства без изменения данных и настроек.";
        value.permissions[0].description = "Просматривать рабочее пространство, сводку расчетов и опубликованные сведения без выхода содержательного текста за границы мобильной карточки.";
      }
      await json(route, value);
      return;
    }
    if (path === "/api/v1/admin/system/status") {
      if (options.systemForbidden) {
        await json(route, errorPayload("PERMISSION_DENIED", "Недостаточно прав для просмотра состояния системы.", false), 403);
        return;
      }
      if (options.systemHttpUnavailable) {
        await json(route, errorPayload("ADMIN_SYSTEM_UNAVAILABLE", "Состояние системы временно недоступно.", true), 503);
        return;
      }
      const value = createAdminSystemStatusFixture();
      if (options.systemUnavailable) {
        value.overall_status = "unavailable";
        value.subsystems.application.status = "unavailable";
        value.subsystems.application.display_text = "Приложение временно недоступно.";
      }
      if (options.longAdminContent) {
        value.subsystems.application.display_text = "Приложение отвечает на запросы, а длинное безопасное описание состояния корректно переносится внутри узкой мобильной карточки.";
      }
      await json(route, value);
      return;
    }
    if (path === "/api/v1/admin/audit") {
      if (options.malformedAudit) {
        await json(route, {
          contract_name: "admin_audit_log_v1",
          schema_version: "1.0.0",
          items: "malformed",
        });
        return;
      }
      const payload = auditPayload(url, options.emptyAudit, options.manyAudit);
      trace.pages.push({
        endpoint: path,
        requestedPage: Number(url.searchParams.get("page") ?? "1"),
        requestedPageSize: Number(url.searchParams.get("page_size") ?? "50"),
        payloadPage: payload.pagination.page,
        firstVisibleText: payload.items[0]?.browser_safe_summary ?? null,
      });
      await json(route, payload);
      return;
    }
    await route.abort("blockedbyclient");
  });
  return trace;
}

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.getByRole("button", { name: theme === "light" ? "Светлая тема" : "Темная тема" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

async function ready(page: Page) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
}

async function screenshot(page: Page, name: string) {
  await ready(page);
  await page.screenshot({ path: `${REVIEW_DIRECTORY}${name}`, fullPage: false });
}

async function placeMobileCardBetweenFixedChrome(page: Page, card: Locator) {
  await card.evaluate((node) => {
    const topbar = document.querySelector<HTMLElement>('header[class*="topbar"]');
    const topbarHeight = topbar?.getBoundingClientRect().height ?? 0;
    const cardTop = node.getBoundingClientRect().top + window.scrollY;
    window.scrollTo({ top: Math.max(0, cardTop - topbarHeight - 16), behavior: "instant" });
  });
  await expect.poll(async () => {
    const [cardBox, topbarBox, navBox] = await Promise.all([
      card.boundingBox(),
      page.locator('header[class*="topbar"]').boundingBox(),
      page.locator('aside[class*="sidebar"]').boundingBox(),
    ]);
    return Boolean(
      cardBox && topbarBox && navBox &&
      cardBox.y >= topbarBox.y + topbarBox.height &&
      cardBox.y + cardBox.height <= navBox.y,
    );
  }).toBe(true);
}

async function expectNoMobileHorizontalOverflow(page: Page, targets: Locator) {
  await expect.poll(() => page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth
  )).toBe(0);
  const overflowingTargets = await targets.evaluateAll((elements) => elements
    .map((element) => ({
      text: element.textContent?.trim().slice(0, 120) ?? "",
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }))
    .filter((value) => value.scrollWidth > value.clientWidth + 1));
  expect(overflowingTargets).toEqual([]);
}

test.describe("Phase E review screenshots", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  for (const theme of ["dark", "light"] as const) {
    test(`login ${theme}`, async ({ page }) => {
      await installApi(page, { authenticated: false, theme });
      await page.goto("/login");
      if (theme === "light") await setTheme(page, theme);
      await expect(page.getByRole("heading", { name: "Войдите в рабочее пространство" })).toBeVisible();
      await screenshot(page, `01-login-${theme}.png`);
    });

    test(`login error ${theme}`, async ({ page }) => {
      await installApi(page, { authenticated: false, loginMode: "invalid" });
      await page.goto("/login");
      if (theme === "light") await setTheme(page, theme);
      await page.getByLabel("Email").fill("wrong@example.org");
      await page.getByLabel("Пароль").fill("Wrong-password-2026");
      await page.getByRole("button", { name: "Войти" }).click();
      await expect(page.getByRole("alert")).toContainText("Не удалось войти");
      await expect(page.getByLabel("Пароль")).toHaveValue("");
      await screenshot(page, `02-login-error-${theme}.png`);
    });

    test(`session profile ${theme}`, async ({ page }) => {
      await installApi(page);
      await page.goto("/");
      if (theme === "light") await setTheme(page, theme);
      await page.getByRole("button", { name: /Мария Соколова/ }).click();
      await expect(page.getByRole("menu")).toContainText("maria.sokolova@example.org");
      await screenshot(page, `03-session-profile-${theme}.png`);
    });

    test(`users ${theme}`, async ({ page }) => {
      await installApi(page);
      await page.goto("/admin/users");
      if (theme === "light") await setTheme(page, theme);
      await expect(page.getByRole("heading", { name: "Пользователи" })).toBeVisible();
      await screenshot(page, `04-users-${theme}.png`);
    });

    test(`user create ${theme}`, async ({ page }) => {
      await installApi(page);
      await page.goto("/admin/users");
      if (theme === "light") await setTheme(page, theme);
      await page.getByRole("button", { name: "Добавить пользователя" }).click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await screenshot(page, `05-user-create-${theme}.png`);
    });

    test(`roles ${theme}`, async ({ page }) => {
      await installApi(page);
      await page.goto("/admin/roles");
      if (theme === "light") await setTheme(page, theme);
      await expect(page.getByRole("heading", { name: "Роли и доступы" })).toBeVisible();
      await screenshot(page, `06-roles-${theme}.png`);
    });

    test(`system ${theme}`, async ({ page }) => {
      await installApi(page);
      await page.goto("/admin/system");
      if (theme === "light") await setTheme(page, theme);
      await expect(page.getByRole("heading", { name: "Состояние системы" })).toBeVisible();
      await screenshot(page, `07-system-${theme}.png`);
    });

    test(`audit ${theme}`, async ({ page }) => {
      await installApi(page);
      await page.goto("/admin/audit");
      if (theme === "light") await setTheme(page, theme);
      await expect(page.getByRole("heading", { name: "Журнал действий" })).toBeVisible();
      await screenshot(page, `08-audit-${theme}.png`);
    });

    test(`forbidden ${theme}`, async ({ page }) => {
      await installApi(page, { role: "viewer" });
      await page.goto("/admin/system");
      if (theme === "light") await setTheme(page, theme);
      await expect(page.getByRole("heading", { name: "Недостаточно прав" })).toBeVisible();
      await expect(page).toHaveURL(/\/admin\/system/);
      await screenshot(page, `09-forbidden-${theme}.png`);
    });
  }

  for (const theme of ["dark", "light"] as const) {
    test(`users mobile ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 812 });
      await installApi(page);
      await page.goto("/admin/users");
      if (theme === "light") await setTheme(page, theme);
      const firstCard = page.locator('article[class*="userCard"]').first();
      await expect(firstCard).toBeVisible();
      await expect(page.getByText("Демонстрационные данные", { exact: true })).toBeVisible();
      await placeMobileCardBetweenFixedChrome(page, firstCard);
      await screenshot(page, `10-users-mobile-${theme}.png`);
    });
  }
});

test.describe("Phase E auth and permission behavior", () => {
  test("protects routes, logs in, bootstraps again and logs out", async ({ page }) => {
    await installApi(page, { authenticated: false });
    await page.goto("/admin/users?status=active");
    await expect(page).toHaveURL(/\/login\?return_to=/);
    await page.getByLabel("Email").fill("maria.sokolova@example.org");
    await page.getByLabel("Пароль").fill("Admin-password-2026");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page).toHaveURL(/\/admin\/users\?status=active/);
    await page.getByRole("button", { name: /Мария Соколова/ }).click();
    await page.getByRole("menuitem", { name: "Выйти" }).click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("keeps a viewer session on 403 and hides admin navigation", async ({ page }) => {
    await installApi(page, { role: "viewer" });
    await page.goto("/admin/audit");
    await expect(page.getByRole("heading", { name: "Недостаточно прав" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Анна Морозова/ })).toBeVisible();
    await expect(page.getByText("Администрирование", { exact: true })).toHaveCount(0);
  });

  test("keeps an analyst in the SPA on permission 403 without exposing admin navigation or logging out", async ({ page }) => {
    await installApi(page, { role: "analyst" });
    await page.goto("/");
    await expect(page.getByRole("button", { name: /Илья Волков/ })).toBeVisible();
    await expect(page.getByText("Администрирование", { exact: true })).toHaveCount(0);
    await expect(page.locator('a[href^="/admin/"]')).toHaveCount(0);

    await page.evaluate(() => {
      history.pushState({}, "", "/admin/users");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    await expect(page).toHaveURL(/\/admin\/users$/);
    await expect(page.getByRole("heading", { name: "Недостаточно прав" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Илья Волков/ })).toBeVisible();
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.getByText("Администрирование", { exact: true })).toHaveCount(0);
  });

  test("renders rate limiting separately and never persists auth state", async ({ page }) => {
    await installApi(page, { authenticated: false, loginMode: "rate-limited" });
    await page.goto("/login");
    await page.getByLabel("Email").fill("missing@example.org");
    await page.getByLabel("Пароль").fill("Wrong-password-2026");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByRole("alert")).toContainText("Слишком много попыток");
    const storedKeys = await page.evaluate(() => [...Object.keys(localStorage), ...Object.keys(sessionStorage)]);
    expect(storedKeys.filter((key) => /auth|session|token|cookie/i.test(key))).toEqual([]);
  });

  test("uses mobile cards without horizontal document overflow", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await installApi(page);
    await page.goto("/admin/users");
    const cards = page.locator('article[class*="userCard"]');
    await expect(cards.first()).toBeVisible();
    await expect(page.getByText("Демонстрационные данные", { exact: true })).toBeVisible();
    await placeMobileCardBetweenFixedChrome(page, cards.last());
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBe(0);
  });

  test("treats a protected 401 as an expired session and preserves the return path", async ({ page }) => {
    await installApi(page, { usersUnauthorized: true });
    await page.goto("/admin/users?status=active");
    await expect(page).toHaveURL(/\/login\?return_to=/);
    await expect(page.getByRole("status")).toContainText("Сессия завершена. Войдите повторно.");
    const returnTo = new URL(page.url()).searchParams.get("return_to");
    expect(returnTo).toBe("/admin/users?status=active");
  });

  test("keeps the authenticated profile after a backend 403", async ({ page }) => {
    await installApi(page, { systemForbidden: true });
    await page.goto("/admin/system");
    await expect(page.getByRole("heading", { name: "Недостаточно прав" })).toBeVisible();
    await expect(page).toHaveURL(/\/admin\/system/);
    await expect(page.getByRole("button", { name: /Мария Соколова/ })).toBeVisible();
  });

  test("shows the browser-safe last-admin conflict without losing the session", async ({ page }) => {
    await installApi(page, { mutationConflict: true });
    await page.goto("/admin/users");
    const row = page.getByRole("row").filter({ hasText: "Мария Соколова" });
    await row.getByRole("button", { name: "Отключить" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Подтвердить" }).click();
    await expect(page.getByRole("alert")).toContainText("Нельзя отключить последнего активного администратора");
    await expect(page.getByRole("button", { name: /Мария Соколова/ })).toBeVisible();
  });

  test("keeps Users URL filters through reload and uses backend filtering", async ({ page }) => {
    await installApi(page);
    await page.goto("/admin/users?page=1&page_size=25&search=%D0%90%D0%BD%D0%BD%D0%B0&role=viewer&status=active&sort=name_asc");
    await expect(page.getByRole("cell", { name: "Анна Морозова" })).toBeVisible();
    await expect(page.getByText("Олег Смирнов", { exact: true })).toHaveCount(0);
    await page.reload();
    await expect(page.getByLabel("Поиск")).toHaveValue("Анна");
    await expect(page.getByLabel("Роль")).toHaveValue("viewer");
  });

  test("Users next and back update URL, requested page, echoed payload page and visible rows", async ({ page }) => {
    const trace = await installApi(page);
    await page.goto("/admin/users?page=1&page_size=2&sort=created_desc");
    await expect(page.getByRole("cell", { name: "Олег Смирнов" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Илья Волков" })).toHaveCount(0);

    await page.getByRole("button", { name: "Далее" }).click();
    await expect.poll(() => new URL(page.url()).searchParams.get("page")).toBe("2");
    await expect.poll(() => trace.pages.at(-1)).toMatchObject({
      endpoint: "/api/v1/admin/users",
      requestedPage: 2,
      requestedPageSize: 2,
      payloadPage: 2,
      firstVisibleText: "Илья Волков",
    });
    await expect(page.getByText("Страница 2 из 2", { exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Илья Волков" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Олег Смирнов" })).toHaveCount(0);

    await page.reload();
    await expect(page.getByRole("cell", { name: "Илья Волков" })).toBeVisible();
    await page.getByRole("button", { name: "Назад" }).click();
    await expect.poll(() => new URL(page.url()).searchParams.get("page")).toBe("1");
    await expect.poll(() => trace.pages.at(-1)).toMatchObject({
      endpoint: "/api/v1/admin/users",
      requestedPage: 1,
      requestedPageSize: 2,
      payloadPage: 1,
      firstVisibleText: "Олег Смирнов",
    });
    await expect(page.getByText("Страница 1 из 2", { exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Олег Смирнов" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Илья Волков" })).toHaveCount(0);
  });

  test("keeps Audit URL filters through reload", async ({ page }) => {
    await installApi(page);
    await page.goto("/admin/audit?page=1&page_size=50&event_type=role_changed&sort=occurred_desc");
    await expect(page.getByRole("cell", { name: "Роль изменена" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Вход отклонен" })).toHaveCount(0);
    await page.reload();
    await expect(page.getByLabel("Событие")).toHaveValue("role_changed");
  });

  test("Audit next and back update URL, requested page, echoed payload page and visible rows", async ({ page }) => {
    const trace = await installApi(page);
    await page.goto("/admin/audit?page=1&page_size=2&sort=occurred_desc");
    await expect(page.getByRole("cell", { name: "Сессии завершены" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Пользователь создан" })).toHaveCount(0);

    await page.getByRole("button", { name: "Далее" }).click();
    await expect.poll(() => new URL(page.url()).searchParams.get("page")).toBe("2");
    await expect.poll(() => trace.pages.at(-1)).toMatchObject({
      endpoint: "/api/v1/admin/audit",
      requestedPage: 2,
      requestedPageSize: 2,
      payloadPage: 2,
      firstVisibleText: "Создана локальная учетная запись пользователя.",
    });
    await expect(page.getByText("Страница 2 из 2", { exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Пользователь создан" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Сессии завершены" })).toHaveCount(0);

    await page.reload();
    await expect(page.getByRole("cell", { name: "Пользователь создан" })).toBeVisible();
    await page.getByRole("button", { name: "Назад" }).click();
    await expect.poll(() => new URL(page.url()).searchParams.get("page")).toBe("1");
    await expect.poll(() => trace.pages.at(-1)).toMatchObject({
      endpoint: "/api/v1/admin/audit",
      requestedPage: 1,
      requestedPageSize: 2,
      payloadPage: 1,
      firstVisibleText: "Активные сеансы пользователя завершены.",
    });
    await expect(page.getByText("Страница 1 из 2", { exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Сессии завершены" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Пользователь создан" })).toHaveCount(0);
  });

  test("blocks role-dependent create and edit controls when the role catalog is unavailable", async ({ page }) => {
    await installApi(page, { rolesUnavailable: true });
    await page.goto("/admin/users");
    await expect(page.getByRole("heading", { name: "Пользователи" })).toBeVisible();
    await expect(page.getByLabel("Роль")).toBeDisabled();
    await expect(page.getByLabel("Роль")).toContainText("Каталог ролей недоступен");
    await expect(page.getByRole("button", { name: "Добавить пользователя" })).toBeDisabled();
    await expect(page.locator("table").getByRole("button", { name: "Изменить" }).first()).toBeDisabled();
    let copy = await page.locator("body").innerText();
    expect(copy).not.toMatch(/admin\.roles\.write|usr_[0-9a-f]{24}|\bviewer\b|\banalyst\b/);

    await page.getByRole("link", { name: "Роли", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Раздел временно недоступен" })).toBeVisible();
    await expect(page.getByText("Каталог ролей временно недоступен.", { exact: true })).toBeVisible();
    copy = await page.locator("body").innerText();
    expect(copy).not.toMatch(/ADMIN_ROLE_CATALOG_UNAVAILABLE|admin_role_catalog_v1|admin\.roles\.write|usr_[0-9a-f]{24}/);
  });

  test("renders controlled admin states for HTTP 503 and malformed contract payloads", async ({ page }) => {
    await installApi(page, { systemHttpUnavailable: true, malformedAudit: true });
    await page.goto("/admin/system");
    await expect(page.getByRole("heading", { name: "Раздел временно недоступен" })).toBeVisible();
    await expect(page.getByText("Состояние системы временно недоступно.", { exact: true })).toBeVisible();
    expect(await page.locator("body").innerText()).not.toMatch(/ADMIN_SYSTEM_UNAVAILABLE|admin_system_status_v1/);

    await page.getByRole("link", { name: "Журнал действий", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Формат ответа не поддерживается" })).toBeVisible();
    await expect(page.getByText("Сервис вернул неподдерживаемый формат данных.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /Мария Соколова/ })).toBeVisible();
    expect(await page.locator("body").innerText()).not.toMatch(/admin_audit_log_v1|malformed|UNSUPPORTED_AUTH_ADMIN_CONTRACT/);
  });

  test("keeps long and high-volume Users, Roles, System and Audit content inside a 375px viewport", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await installApi(page, { manyUsers: true, manyAudit: true, longAdminContent: true });

    await page.goto("/admin/users");
    const userCards = page.locator('article[class*="userCard"]');
    await expect(userCards).toHaveCount(25);
    await expect(userCards.first().getByText("Александра-Екатерина Константинопольская с очень длинным отображаемым именем", { exact: true })).toBeVisible();
    await userCards.last().scrollIntoViewIfNeeded();
    await expectNoMobileHorizontalOverflow(page, userCards);

    await page.goto("/admin/roles");
    const roleCards = page.locator('article[class*="roleCard"]');
    await expect(roleCards).toHaveCount(3);
    await roleCards.last().scrollIntoViewIfNeeded();
    await expectNoMobileHorizontalOverflow(page, roleCards);

    await page.goto("/admin/system");
    const systemCards = page.locator('article[class*="systemCard"]');
    await expect(systemCards).toHaveCount(6);
    await systemCards.last().scrollIntoViewIfNeeded();
    await expectNoMobileHorizontalOverflow(page, systemCards);

    await page.goto("/admin/audit");
    const auditCards = page.locator('article[class*="auditCard"]');
    await expect(auditCards).toHaveCount(50);
    await expect(auditCards.first().getByText("Александра-Екатерина Константинопольская — администратор длительной мобильной проверки", { exact: true })).toBeVisible();
    await auditCards.last().scrollIntoViewIfNeeded();
    await expectNoMobileHorizontalOverflow(page, auditCards);
  });

  test("renders controlled empty and unavailable states", async ({ page }) => {
    await installApi(page, { emptyUsers: true, emptyAudit: true, systemUnavailable: true });
    await page.goto("/admin/users");
    await expect(page.getByRole("heading", { name: "Пользователи не найдены" })).toBeVisible();
    await page.goto("/admin/audit");
    await expect(page.getByRole("heading", { name: "События не найдены" })).toBeVisible();
    await page.goto("/admin/system");
    await expect(page.getByText("Недоступно", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Приложение временно недоступно.")).toBeVisible();
  });

  test("traps modal Tab focus, restores focus and leaves zero active animations under reduced motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await installApi(page);
    await page.goto("/admin/users");
    const opener = page.getByRole("button", { name: "Добавить пользователя" });
    await opener.focus();
    await opener.press("Enter");
    const dialog = page.getByRole("dialog");
    const firstFocusable = dialog.getByRole("button", { name: "Закрыть" });
    const lastFocusable = dialog.getByRole("button", { name: "Создать" });
    await expect(dialog).toBeVisible();
    await expect(firstFocusable).toBeFocused();
    await lastFocusable.focus();
    await page.keyboard.press("Tab");
    await expect(firstFocusable).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(lastFocusable).toBeFocused();
    await expect.poll(() => page.evaluate(() =>
      document.getAnimations().filter((animation) => animation.playState === "running").length
    )).toBe(0);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  });

  test("never renders sensitive auth or internal identifiers in user-facing copy", async ({ page }) => {
    await installApi(page);
    const forbidden = [
      /session_id/i,
      /user_id/i,
      /request_id/i,
      /password_hash/i,
      /session token/i,
      /\bcookie\b/i,
      /\bsqlite\b/i,
      /\bfilesystem\b/i,
      /stack trace/i,
      /\borigin\b/i,
      /\bhost\b/i,
      /argon2id/i,
    ];
    for (const path of ["/admin/users", "/admin/roles", "/admin/system", "/admin/audit"] as const) {
      await page.goto(path);
      await expect(page.locator("h1")).toBeVisible();
      const copy = await page.locator("body").innerText();
      for (const pattern of forbidden) expect(copy).not.toMatch(pattern);
    }
  });

  for (const theme of ["dark", "light"] as const) {
    test(`small auth and admin copy meets WCAG contrast in ${theme} theme`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await installApi(page, { authenticated: false, theme });
      const samples: ContrastSample[] = [];

      await page.goto("/login");
      if (theme === "light") await setTheme(page, theme);
      samples.push(...await measureContentContrast(page, PHASE_E_CONTRAST_TARGETS));
      await page.getByLabel("Email").fill("maria.sokolova@example.org");
      await page.getByLabel("Пароль").fill("Admin-password-2026");
      await page.getByRole("button", { name: "Войти" }).click();
      await expect(page).toHaveURL("/");

      await page.goto("/admin/users");
      await expect(page.getByRole("heading", { name: "Пользователи" })).toBeVisible();
      samples.push(...await measureContentContrast(page, PHASE_E_CONTRAST_TARGETS));
      await page.getByRole("button", { name: "Добавить пользователя" }).click();
      await expect(page.getByRole("dialog")).toBeVisible();
      samples.push(...await measureContentContrast(page, PHASE_E_CONTRAST_TARGETS));
      await page.getByRole("dialog").getByRole("button", { name: "Закрыть" }).click();

      await page.goto("/admin/roles");
      await expect(page.getByRole("heading", { name: "Роли и доступы" })).toBeVisible();
      samples.push(...await measureContentContrast(page, PHASE_E_CONTRAST_TARGETS));
      await page.goto("/admin/system");
      await expect(page.getByRole("heading", { name: "Состояние системы" })).toBeVisible();
      samples.push(...await measureContentContrast(page, PHASE_E_CONTRAST_TARGETS));
      await page.goto("/admin/audit");
      await expect(page.getByRole("heading", { name: "Журнал действий" })).toBeVisible();
      samples.push(...await measureContentContrast(page, PHASE_E_CONTRAST_TARGETS));

      await page.setViewportSize({ width: 375, height: 812 });
      await page.goto("/admin/users");
      await expect(page.locator('article[class*="userCard"]').first()).toBeVisible();
      samples.push(...await measureContentContrast(page, PHASE_E_CONTRAST_TARGETS));
      await page.goto("/admin/audit");
      await expect(page.locator('article[class*="auditCard"]').first()).toBeVisible();
      samples.push(...await measureContentContrast(page, PHASE_E_CONTRAST_TARGETS));

      const coveredTargets = [...new Set(samples.map((sample) => sample.target))];
      for (const target of PHASE_E_CONTRAST_TARGETS) {
        expect(coveredTargets, `${target.name} was not measured`).toContain(target.name);
      }
      const minimum = samples.reduce((current, sample) =>
        sample.ratio < current.ratio ? sample : current
      );
      test.info().annotations.push({
        type: "contrast",
        description: `${minimum.ratio.toFixed(3)}:1 — ${minimum.text}`,
      });
      console.info(
        `[phase-e-contrast:${theme}] minimum ${minimum.ratio.toFixed(3)}:1`,
        JSON.stringify(minimum),
      );
      expect(minimum.ratio, JSON.stringify(minimum, null, 2)).toBeGreaterThanOrEqual(4.5);
    });
  }
});
