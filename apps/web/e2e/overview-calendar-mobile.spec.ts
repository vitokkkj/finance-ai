import { expect, test } from "@playwright/test";

import { mockFinanceApi } from "./api-mocks";

test("o seletor de mês no celular permanece fixo, inteiro e selecionável", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await mockFinanceApi(page);
  await page.goto("/?view=finance&section=overview");

  const trigger = page.getByRole("button", { name: "Mês analisado" });
  await trigger.click();

  const dialog = page.getByRole("dialog", { name: "Mês analisado" });
  const monthButtons = dialog.locator(".sophia-month-grid button");
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveCSS("position", "fixed");
  await expect(monthButtons).toHaveCount(12);
  for (const month of await monthButtons.all()) {
    await expect(month).toBeInViewport();
  }

  const beforeScroll = await dialog.boundingBox();
  expect(beforeScroll).not.toBeNull();
  expect(beforeScroll!.x).toBeGreaterThanOrEqual(0);
  expect(beforeScroll!.x + beforeScroll!.width).toBeLessThanOrEqual(390);
  expect(beforeScroll!.y + beforeScroll!.height).toBeLessThanOrEqual(844);

  const financeViewport = page.locator(".assistant-finance-view");
  await financeViewport.evaluate((element) => {
    element.scrollTop = 180;
  });
  await expect.poll(() => financeViewport.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  const afterScroll = await dialog.boundingBox();
  expect(afterScroll).not.toBeNull();
  expect(Math.abs(afterScroll!.y - beforeScroll!.y)).toBeLessThan(1);

  await dialog.getByRole("button", { name: "nov", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toContainText("novembro de 2026");
  await expect.poll(() => state.dashboardQueries).toContain("?year=2026&month=11");
});
