import { expect, test } from "@playwright/test";

import { mockFinanceApi } from "./api-mocks";

test.beforeEach(async ({ page }) => {
  await page.clock.install({ time: new Date("2026-10-12T12:00:00-03:00") });
});

test("Cartões registra compra parcelada e preserva o fluxo à vista", async ({ page }) => {
  const state = await mockFinanceApi(page, { categoryBreakdown: true });
  await page.goto("/?view=finance&section=cards");

  await page.getByRole("button", { name: "＋ Nova compra" }).click();
  const form = page.locator("form.editor-form").filter({ hasText: "Registrar compra" });
  await form.getByLabel("Cartão").selectOption("synthetic-card-nubank");
  await form.getByLabel("Categoria").selectOption("synthetic-category-food");
  await form.getByLabel("Descrição").fill("Pneus Twister");
  await form.getByLabel("Parcelas").selectOption("5");
  await form.getByLabel("Valor total").fill("905,05");
  await form.getByRole("button", { name: "Registrar compra", exact: true }).click();

  await expect.poll(() => state.cardPurchasePlanRequests.length).toBe(1);
  expect(state.cardPurchasePlanRequests).toEqual([
    {
      credit_card_id: "synthetic-card-nubank",
      category_id: "synthetic-category-food",
      description: "Pneus Twister",
      total_amount: "905.05",
      installment_count: 5,
      occurred_at: "2026-10-12",
      notes: null,
    },
  ]);
  expect(state.cardPurchaseRequests).toHaveLength(0);

  await page.getByRole("button", { name: "＋ Nova compra" }).click();
  const singlePurchaseForm = page.locator("form.editor-form").filter({ hasText: "Registrar compra" });
  await singlePurchaseForm.getByLabel("Cartão").selectOption("synthetic-card-nubank");
  await expect(singlePurchaseForm.getByLabel("Parcelas")).toHaveValue("1");
  await singlePurchaseForm.getByLabel("Descrição").fill("Compra à vista");
  await singlePurchaseForm.getByLabel("Valor").fill("34,90");
  await singlePurchaseForm.getByRole("button", { name: "Registrar compra", exact: true }).click();

  await expect.poll(() => state.cardPurchaseRequests.length).toBe(1);
  expect(state.cardPurchaseRequests).toEqual([
    {
      credit_card_id: "synthetic-card-nubank",
      category_id: "synthetic-category-food",
      description: "Compra à vista",
      amount: "34.90",
      occurred_at: "2026-10-12",
      notes: null,
    },
  ]);
});

test("o chat apresenta a prévia e o resultado de uma compra parcelada", async ({ page }) => {
  await mockFinanceApi(page);
  let confirmed = false;
  const pendingItem = {
    type: "confirmation",
    tool_call_id: "synthetic-installment-confirmation",
    status: "pending",
    data: {
      title: "Confirme a compra parcelada",
      changes: {
        "Cartão": "Nubank",
        "Descrição": "Pneus Twister",
        "Valor total": "R$ 905,05",
        "Parcelas": "5",
        "Parcela 1/5": "R$ 181,01 · vence 11/11/2026",
      },
      message: "Cada parcela será registrada como despesa na fatura do respectivo ciclo.",
    },
  };
  const installmentCycles = [
    ["2026-11-04", "2026-11-11"],
    ["2026-12-04", "2026-12-11"],
    ["2027-01-04", "2027-01-11"],
    ["2027-02-04", "2027-02-11"],
    ["2027-03-04", "2027-03-11"],
  ];
  const planItem = {
    type: "card_purchase_plan",
    data: {
      credit_card_name: "Nubank",
      total_amount: "905.05",
      installment_count: 5,
      installments: installmentCycles.map(([closingDate, dueDate], index) => ({
        number: index + 1,
        amount: "181.01",
        closing_date: closingDate,
        due_date: dueDate,
        transaction_id: `synthetic-installment-${index + 1}`,
      })),
    },
  };

  await page.route("**/api/ai/conversations/synthetic-conversation", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "synthetic-conversation",
        title: "Compra parcelada Nubank",
        created_at: "2026-10-12T12:00:00-03:00",
        updated_at: "2026-10-12T12:00:00-03:00",
        messages: [
          { id: "installment-user", role: "USER", content: "Pneus Twister em 5 parcelas no Nubank" },
          {
            id: "installment-assistant",
            role: "ASSISTANT",
            content: confirmed ? "Compra parcelada registrada." : "Revise o parcelamento antes de confirmar.",
            structured_content: [confirmed ? planItem : pendingItem],
          },
        ],
      }),
    });
  });
  await page.route("**/api/ai/conversations/*/messages", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: `event: text_delta\ndata: ${JSON.stringify({ text: "Revise o parcelamento antes de confirmar." })}\n\nevent: structured\ndata: ${JSON.stringify({ items: [pendingItem] })}\n\nevent: done\ndata: {}\n\n`,
    });
  });
  await page.route("**/api/ai/conversations/*/tool-calls/*/confirm", async (route) => {
    confirmed = true;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "SUCCEEDED" }) });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Nova conversa" }).click();
  await page.getByRole("textbox", { name: "Mensagem para o assistente" }).fill(
    "Registre Pneus Twister por R$ 905,05 em 5 parcelas no Nubank.",
  );
  await page.getByRole("button", { name: "Enviar mensagem" }).click();

  const confirmation = page.locator(".assistant-confirmation");
  await expect(confirmation).toContainText("Confirme a compra parcelada");
  await expect(confirmation).toContainText("Parcela 1/5");
  await confirmation.getByRole("button", { name: "Confirmar" }).click();

  const result = page.locator(".assistant-data-card").filter({ hasText: "Compra parcelada registrada" });
  await expect(result).toContainText("R$ 905,05");
  await expect(result).toContainText("Parcela 5");
  await expect(result).toContainText("Vence 11 de mar.");
});
