import { expect, test, type Page } from "@playwright/test";

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.addInitScript((value) => {
    window.localStorage.setItem("mmm-frontend-theme", value);
  }, theme);
}

for (const theme of ["dark", "light"] as const) {
  test(`result overview ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setTheme(page, theme);
    await page.goto("/calculations/demo-safe/result");
    await expect(page.getByText("Демонстрационные данные")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Demo campaign 1" })).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(250);
    await page.screenshot({
      path: `artifacts/visual-qa/result-overview-${theme}-1440x900.png`,
      fullPage: false,
    });
    await page.screenshot({
      path: `artifacts/visual-qa/result-overview-${theme}-full.png`,
      fullPage: true,
    });
  });
}

test("gate-blocked S6 exposes its reason", async ({ page }) => {
  await page.goto("/calculations/gate-blocked/result");
  await expect(page.getByText("S6 недоступен")).toBeVisible();
  await expect(page.getByText(/каналы зафиксированы gate policy/i).first()).toBeVisible();
});

test("collapsed-sidebar breakpoint has no horizontal overflow", async ({ page }) => {
  for (const width of [1099, 1100, 1101]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/calculations/demo-safe/result");
    const hasOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(hasOverflow).toBe(false);
  }
});
