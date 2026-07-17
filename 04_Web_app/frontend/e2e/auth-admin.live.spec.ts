import { expect, test } from "@playwright/test";

const LIVE_ENABLED = process.env.PHASE_E_LIVE === "true";
const ADMIN_EMAIL = process.env.PHASE_E_LIVE_ADMIN_EMAIL ?? "";
const ADMIN_PASSWORD = process.env.PHASE_E_LIVE_ADMIN_PASSWORD ?? "";
const BACKEND_URL = process.env.PHASE_E_LIVE_BACKEND_URL ?? "http://127.0.0.1:8765";
const FRONTEND_ORIGIN = process.env.PHASE_E_LIVE_FRONTEND_ORIGIN ?? "http://127.0.0.1:4173";

test.describe("Phase E live backend acceptance", () => {
  test.skip(!LIVE_ENABLED, "Set PHASE_E_LIVE=true to run against a real local backend.");
  test.describe.configure({ mode: "serial" });

  test("uses real cookies, permissions and admin mutations without route interception", async ({ page, playwright }) => {
    test.setTimeout(120_000);
    expect(ADMIN_EMAIL).not.toBe("");
    expect(ADMIN_PASSWORD).not.toBe("");
    const consoleIssues: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "warning" || message.type() === "error") {
        consoleIssues.push(`${message.type()}: ${message.text()}`);
      }
    });
    page.on("pageerror", (error) => consoleIssues.push(`pageerror: ${error.message}`));

    const suffix = Date.now().toString(36);
    const pilotEmail = `phase-e-live-${suffix}@example.org`;
    const pilotPassword = `Pilot-${suffix}-Password-2026`;
    const pilotName = `Пилот ${suffix}`;
    const renamedPilot = `Аналитик ${suffix}`;

    await page.goto("/admin/users?status=active&sort=name_asc");
    await expect(page).toHaveURL(/\/login\?return_to=/);
    await page.getByLabel("Email").fill(ADMIN_EMAIL);
    await page.getByLabel("Пароль").fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page).toHaveURL(/\/admin\/users\?status=active&sort=name_asc/);
    await expect(page.getByRole("heading", { name: "Пользователи" })).toBeVisible();

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Планируйте бюджет и проверяйте результат в одном месте" })).toBeVisible();
    await page.getByRole("button", { name: new RegExp("Администратор приемки") }).click();
    await page.getByRole("menuitem", { name: "Выйти" }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.getByLabel("Email").fill(ADMIN_EMAIL);
    await page.getByLabel("Пароль").fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page).toHaveURL("/");
    await page.goto("/admin/users?status=active&sort=name_asc");
    await expect(page.getByRole("heading", { name: "Пользователи" })).toBeVisible();

    const createButton = page.getByRole("button", { name: "Добавить пользователя" });
    await expect(createButton).toBeEnabled();
    await createButton.click();
    const createDialog = page.getByRole("dialog", { name: "Новый пользователь" });
    await createDialog.getByLabel("Имя", { exact: true }).fill(pilotName);
    await createDialog.getByLabel("Email", { exact: true }).fill(pilotEmail);
    await createDialog.locator("select").selectOption("viewer");
    await createDialog.locator('input[type="password"]').fill(pilotPassword);
    await createDialog.getByRole("button", { name: "Создать" }).click();
    await expect(createDialog).toBeHidden();

    const search = page.getByLabel("Поиск");
    await search.fill(pilotEmail);
    await page.getByRole("button", { name: "Найти" }).click();
    await expect(page).toHaveURL(new RegExp(`search=${encodeURIComponent(pilotEmail)}`));
    const pilotRow = page.getByRole("row", { name: new RegExp(pilotEmail) });
    await expect(pilotRow).toContainText("Наблюдатель");

    const isolatedViewerSession = await playwright.request.newContext({
      baseURL: BACKEND_URL,
      extraHTTPHeaders: { Origin: FRONTEND_ORIGIN },
    });
    const viewerLogin = await isolatedViewerSession.post("/api/v1/auth/login", {
      data: { email: pilotEmail, password: pilotPassword },
    });
    expect(viewerLogin.status()).toBe(200);
    const viewerSession = await isolatedViewerSession.get("/api/v1/auth/session");
    const viewerSessionBody = await viewerSession.json();
    expect(viewerSessionBody.authenticated).toBe(true);
    expect(viewerSessionBody.user.role.role_id).toBe("viewer");
    expect((await isolatedViewerSession.get("/api/v1/admin/system/status")).status()).toBe(403);
    expect((await isolatedViewerSession.post("/api/v1/auth/logout")).status()).toBe(200);
    await isolatedViewerSession.dispose();

    await pilotRow.getByRole("button", { name: "Изменить" }).click();
    const editDialog = page.getByRole("dialog", { name: "Настройки пользователя" });
    await editDialog.getByLabel("Имя", { exact: true }).fill(renamedPilot);
    await editDialog.locator("select").selectOption("analyst");
    await editDialog.getByRole("button", { name: "Сохранить" }).click();
    await expect(editDialog).toBeHidden();
    await expect(pilotRow).toContainText(renamedPilot);
    await expect(pilotRow).toContainText("Аналитик");

    const isolatedPilotSession = await playwright.request.newContext({
      baseURL: BACKEND_URL,
      extraHTTPHeaders: { Origin: FRONTEND_ORIGIN },
    });
    const pilotLogin = await isolatedPilotSession.post("/api/v1/auth/login", {
      data: { email: pilotEmail, password: pilotPassword },
    });
    expect(pilotLogin.status()).toBe(200);
    const analystSession = await isolatedPilotSession.get("/api/v1/auth/session");
    expect((await analystSession.json()).user.role.role_id).toBe("analyst");
    const forbidden = await isolatedPilotSession.get("/api/v1/admin/system/status");
    expect(forbidden.status()).toBe(403);
    const stillAuthenticated = await isolatedPilotSession.get("/api/v1/auth/session");
    expect((await stillAuthenticated.json()).authenticated).toBe(true);

    await page.reload();
    const refreshedPilotRow = page.getByRole("row", { name: new RegExp(pilotEmail) });
    await expect(refreshedPilotRow).toContainText("1");
    await refreshedPilotRow.getByRole("button", { name: "Завершить сессии" }).click();
    const revokeDialog = page.getByRole("dialog", { name: "Завершить активные сессии?" });
    await revokeDialog.getByRole("button", { name: "Подтвердить" }).click();
    await expect(revokeDialog).toBeHidden();
    const revokedSession = await isolatedPilotSession.get("/api/v1/auth/session");
    expect((await revokedSession.json()).authenticated).toBe(false);
    await isolatedPilotSession.dispose();

    await page.getByLabel("Статус").selectOption("");
    await expect(page).not.toHaveURL(/status=active/);
    await refreshedPilotRow.getByRole("button", { name: "Отключить" }).click();
    const disableDialog = page.getByRole("dialog", { name: "Отключить пользователя?" });
    await disableDialog.getByRole("button", { name: "Подтвердить" }).click();
    await expect(disableDialog).toBeHidden();
    await expect(refreshedPilotRow).toContainText("Отключен");
    await refreshedPilotRow.getByRole("button", { name: "Включить" }).click();
    const enableDialog = page.getByRole("dialog", { name: "Включить пользователя?" });
    await enableDialog.getByRole("button", { name: "Подтвердить" }).click();
    await expect(enableDialog).toBeHidden();
    await expect(refreshedPilotRow).toContainText("Активен");

    await page.goto("/admin/roles");
    await expect(page.getByRole("heading", { name: "Роли и доступы" })).toBeVisible();
    await expect(page.getByText("admin.users.write", { exact: true })).toHaveCount(0);
    await page.goto("/admin/system");
    await expect(page.getByRole("heading", { name: "Состояние системы" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Пользователи и сессии" })).toBeVisible();
    await page.goto("/admin/audit?event_type=user_created&sort=occurred_desc");
    await expect(page.getByRole("heading", { name: "Журнал действий" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Пользователь создан", exact: true })).not.toHaveCount(0);
    await expect(page).toHaveURL(/event_type=user_created/);

    const adminApi = await playwright.request.newContext({
      baseURL: BACKEND_URL,
      extraHTTPHeaders: { Origin: FRONTEND_ORIGIN },
    });
    const adminLogin = await adminApi.post("/api/v1/auth/login", {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    });
    expect(adminLogin.status()).toBe(200);
    const users = await adminApi.get("/api/v1/admin/users?search=" + encodeURIComponent(ADMIN_EMAIL));
    expect(users.status()).toBe(200);
    const adminUserId = (await users.json()).items[0]?.user_id as string | undefined;
    expect(adminUserId).toMatch(/^usr_[0-9a-f]{24}$/);
    const lastAdminProtection = await adminApi.post(`/api/v1/admin/users/${adminUserId}/disable`);
    expect(lastAdminProtection.status()).toBe(409);
    const revokeAdmin = await adminApi.post(`/api/v1/admin/users/${adminUserId}/sessions/revoke`);
    expect(revokeAdmin.status()).toBe(200);
    await adminApi.dispose();

    await page.getByRole("link", { name: "Пользователи", exact: true }).click();
    await expect(page).toHaveURL(/\/login\?return_to=/);
    await expect(page.getByRole("status")).toContainText("Сессия завершена. Войдите повторно.");
    await page.getByLabel("Email").fill(ADMIN_EMAIL);
    await page.getByLabel("Пароль").fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByRole("heading", { name: "Пользователи" })).toBeVisible();

    await page.setViewportSize({ width: 375, height: 812 });
    await expect(page.locator('article[class*="userCard"]').first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBe(0);
    await page.setViewportSize({ width: 1440, height: 900 });

    await page.getByRole("button", { name: new RegExp("Администратор приемки") }).click();
    await page.getByRole("menuitem", { name: "Выйти" }).click();
    await expect(page).toHaveURL(/\/login/);
    const storageKeys = await page.evaluate(() => [...Object.keys(localStorage), ...Object.keys(sessionStorage)]);
    expect(storageKeys.filter((key) => /auth|session|token|cookie/i.test(key))).toEqual([]);
    const expectedUnauthorizedNetwork = consoleIssues.filter((message) =>
      /Failed to load resource: the server responded with a status of 401 \(Unauthorized\)/.test(message)
    );
    expect(expectedUnauthorizedNetwork.length).toBeGreaterThan(0);
    expect(consoleIssues.filter((message) => !expectedUnauthorizedNetwork.includes(message))).toEqual([]);
  });
});
