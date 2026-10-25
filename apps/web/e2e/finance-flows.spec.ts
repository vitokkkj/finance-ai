import { expect, test } from "@playwright/test";

import { mockFinanceApi } from "./api-mocks";

test.beforeEach(async ({ page }) => {
  await page.clock.install({ time: new Date("2026-10-12T12:00:00-03:00") });
});

test("deeplink e histórico do navegador acompanham a seção financeira", async ({ page }) => {
  await mockFinanceApi(page, { largeLists: true });
  await page.goto("/");

  await page.getByRole("button", { name: "Lançamentos", exact: true }).click();
  await expect(page).toHaveURL(/view=finance&section=transactions/);
  await page.getByRole("button", { name: "Categorias", exact: true }).click();
  await expect(page).toHaveURL(/view=finance&section=categories/);
  await page.getByRole("button", { name: "Ver lançamentos da categoria Categoria 4" }).click();
  await expect(page).toHaveURL(/view=finance&section=transactions/);

  await page.goBack();
  await expect(page).toHaveURL(/view=finance&section=categories/);
  await expect(page.getByRole("heading", { name: "Categorias", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/view=finance&section=transactions/);
  await page.goBack();
  await expect(page).toHaveURL("http://127.0.0.1:4173/");
  await expect(page.getByRole("textbox", { name: "Mensagem para o assistente" })).toBeVisible();

  await page.goForward();
  await expect(page).toHaveURL(/view=finance&section=transactions/);
  await page.goForward();
  await expect(page).toHaveURL(/view=finance&section=categories/);
  await page.goForward();
  await expect(page).toHaveURL(/view=finance&section=transactions/);
});

test("uma seção financeira pode ser aberta por URL direta", async ({ page }) => {
  await mockFinanceApi(page);
  await page.goto("/?view=finance&section=transactions");

  await expect(page).toHaveURL(/view=finance&section=transactions/);
  await expect(page.getByRole("heading", { name: "Receitas, despesas e movimentos", exact: true })).toBeVisible();
});

test("os filtros de lançamentos mostram os totais de todos os resultados", async ({ page }) => {
  const state = await mockFinanceApi(page, { largeLists: true });
  await page.goto("/?view=finance&section=transactions");

  const filters = page.locator(".filter-form");
  await filters.getByLabel("Tipo").selectOption("EXPENSE");
  await filters.getByRole("button", { name: "Filtrar" }).click();

  const summary = page.getByRole("region", { name: "Resumo dos lançamentos filtrados" });
  await expect(summary).toContainText("24 lançamentos correspondentes, em todas as páginas");
  await expect(summary).toContainText("Despesas");
  await expect(summary).toContainText("R$ 288,00");
  expect(state.transactionQueries.some((query) => query.includes("type=EXPENSE"))).toBe(true);
});

test("o indicador de pensamento continua animado com movimento reduzido no sistema", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockFinanceApi(page);

  let releaseResponse: (() => void) | undefined;
  await page.route("**/api/ai/conversations/*/messages", async (route) => {
    await new Promise<void>((resolve) => {
      releaseResponse = resolve;
    });
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: 'event: done\ndata: {"status":"ok"}\n\n',
    });
  });

  await page.goto("/");
  await page.getByRole("textbox", { name: "Mensagem para o assistente" }).fill("Como está meu mês?");
  await page.getByRole("button", { name: "Enviar mensagem" }).click();

  const spinner = page.locator(".assistant-pending-icon");
  await expect(spinner).toBeVisible();
  await expect.poll(() => spinner.evaluate((element) => {
    const style = getComputedStyle(element);
    return [style.animationName, style.animationDuration, style.animationIterationCount];
  })).toEqual(["assistant-status-rotate", "1.2s", "infinite"]);

  releaseResponse?.();
  await expect(page.locator(".assistant-pending-card")).toHaveCount(0);
});

test("os campos de login mantêm fonte de 16 px em uma tela de iPhone", async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    timezoneId: "America/Sao_Paulo",
  });
  const page = await context.newPage();
  await mockFinanceApi(page, { authenticated: false });
  await page.goto("/");

  const email = page.getByLabel("E-mail", { exact: true });
  const password = page.getByLabel("Senha", { exact: true });
  await expect(email).toBeVisible();
  await expect(password).toBeVisible();
  for (const field of [email, password]) {
    const fontSize = await field.evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize));
    expect(fontSize).toBeGreaterThanOrEqual(16);
  }
  await context.close();
});

test("tabelas financeiras cabem na largura do celular sem esconder valores", async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    timezoneId: "America/Sao_Paulo",
  });
  const page = await context.newPage();
  await mockFinanceApi(page, { largeLists: true });
  await page.goto("/?view=finance&section=transactions");
  await expect(page.locator(".transaction-table tbody tr").first()).toBeVisible();
  await expect(page.locator('.transaction-table td[data-label="Valor"]').first()).toBeVisible();

  const tableFits = async () => page.locator(".table-wrap").evaluateAll((wrappers) =>
    wrappers.every((wrapper) => wrapper.scrollWidth <= wrapper.clientWidth + 1),
  );
  expect(await tableFits()).toBe(true);

  for (const [section, label] of [["accounts", "Contas"], ["categories", "Categorias"], ["cards", "Cartões"]] as const) {
    await page.goto(`/?view=finance&section=${section}`);
    await expect(page.getByRole("heading", { name: label, exact: true })).toBeVisible();
    await expect.poll(tableFits).toBe(true);
    if (section === "cards") {
      await expect(page.locator('td[data-label="Disponível"]').first()).toBeVisible();
      await expect(page.locator('td[data-label="Em aberto"]').first()).toBeVisible();
    }
  }
  await context.close();
});

test("atalho em lançamentos abre o formulário de compra no cartão", async ({ page }) => {
  await mockFinanceApi(page);
  await page.goto("/?view=finance&section=transactions");

  await page.getByRole("button", { name: "Compra no cartão", exact: true }).click();

  await expect(page).toHaveURL(/view=finance&section=cards/);
  const purchaseHeading = page.getByRole("heading", { name: "Registrar compra", exact: true });
  await expect(purchaseHeading).toBeVisible();
  await expect(purchaseHeading).toBeFocused();
  const purchaseForm = page.locator("form.editor-form").filter({ hasText: "Registrar compra" });
  await expect(purchaseForm.locator("select").first()).toBeVisible();
  await expect(purchaseForm.getByLabel("Descrição")).toBeVisible();
});

test("o gesto de borda no celular abre o menu sem voltar ao chat anterior", async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    reducedMotion: "reduce",
    timezoneId: "America/Sao_Paulo",
  });
  const page = await context.newPage();
  await page.clock.install({ time: new Date("2026-10-12T12:00:00-03:00") });
  await mockFinanceApi(page);
  await page.goto("/?view=finance&section=transactions");
  await expect(page.getByRole("heading", { name: "Receitas, despesas e movimentos", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Abrir menu de navegação" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Abrir menu de navegação" })).toBeVisible();

  const edgeTouchPrevented = await page.evaluate(() => {
    const layout = document.querySelector(".assistant-layout");
    if (!(layout instanceof HTMLElement)) throw new Error("A área de trabalho não foi encontrada.");
    const touch = new Touch({ identifier: 1, target: layout, clientX: 1, clientY: 160 });
    const event = new TouchEvent("touchstart", {
      bubbles: true,
      cancelable: true,
      touches: [touch],
      targetTouches: [touch],
      changedTouches: [touch],
    });
    layout.dispatchEvent(event);
    return event.defaultPrevented;
  });
  expect(edgeTouchPrevented).toBe(true);

  await page.evaluate(() => {
    const layout = document.querySelector(".assistant-layout");
    if (!(layout instanceof HTMLElement)) throw new Error("A área de trabalho não foi encontrada.");
    const touch = new Touch({ identifier: 1, target: layout, clientX: 140, clientY: 164 });
    layout.dispatchEvent(new TouchEvent("touchend", {
      bubbles: true,
      cancelable: true,
      touches: [],
      targetTouches: [],
      changedTouches: [touch],
    }));
  });
  await expect(page.getByRole("button", { name: "Fechar menu" })).toBeVisible();
  await expect(page).toHaveURL(/view=finance&section=transactions/);
  await context.close();
});

test("a consulta financeira oferece retry quando o carregamento falha", async ({ page }) => {
  // Next's development Strict Mode starts the mount effect twice.
  await mockFinanceApi(page, { largeLists: true, failTransactionsRequests: 2 });
  await page.goto("/");
  await page.getByRole("button", { name: "Lançamentos", exact: true }).click();

  const financeLoadError = page.locator(".workspace-notice[role='alert']");
  await expect(financeLoadError).toContainText("A consulta de lançamentos falhou.");
  await financeLoadError.getByRole("button", { name: "Tentar carregar novamente" }).click();
  await expect(page.locator(".transaction-table tbody tr")).toHaveCount(15);
});

test("a previsão do overview consulta e apresenta o mês futuro escolhido", async ({
  page,
}) => {
  const state = await mockFinanceApi(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Visão geral", exact: true }).click();
  const monthPicker = page.getByRole("button", { name: "Mês analisado" });
  await monthPicker.click();
  const monthDialog = page.getByRole("dialog", { name: "Mês analisado" });
  await monthDialog.getByRole("button", { name: "nov", exact: true }).click();

  const forecast = page.getByRole("region", {
    name: "Contas a pagar previstas",
  });
  await expect(forecast).toContainText("Aluguel previsto em novembro");
  await expect(forecast).toContainText("R$ 812,30");
  await expect(forecast).not.toContainText("Conta sintética de outubro");
  expect(state.dashboardQueries).toContain("?year=2026&month=11");
});

test("a lista de pagamentos previstos no overview pagina além de 15 itens", async ({ page }) => {
  await mockFinanceApi(page, { largeLists: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Visão geral", exact: true }).click();

  const forecast = page.getByRole("region", { name: "Contas a pagar previstas" });
  await expect(forecast.locator(".forecast-row")).toHaveCount(15);
  await forecast.getByRole("navigation", { name: "Paginação das contas previstas" }).getByRole("button", { name: "Próxima" }).click();
  await expect(forecast.locator(".forecast-row")).toHaveCount(6);
});

test("a conversa envia o mês pedido e mostra a previsão estruturada desse período", async ({
  page,
}) => {
  const state = await mockFinanceApi(page);
  await page.goto("/");

  const prompt = "Quais são meus gastos previstos para novembro de 2026?";
  await page
    .getByRole("textbox", { name: "Mensagem para o assistente" })
    .fill(prompt);
  await page.getByRole("button", { name: "Enviar mensagem" }).click();

  await expect(
    page.getByText("Aqui está a previsão sintética de novembro.", {
      exact: true,
    }),
  ).toBeVisible();
  const forecast = page
    .locator(".assistant-data-card")
    .filter({ hasText: "Previsão do mês" });
  await expect(forecast).toContainText("Fatura sintética Nubank");
  await expect(forecast).toContainText("R$ 812,30");
  expect(state.chatPrompts).toEqual([prompt]);
});

test("a pessoa usuária pode baixar a própria exportação de dados", async ({
  page,
}) => {
  await mockFinanceApi(page);
  await page.goto("/");

  await page
    .getByRole("button", { name: "Minha conta de Pessoa de teste" })
    .click();
  const downloadReady = page.waitForEvent("download");
  await page.getByRole("button", { name: "Baixar meus dados" }).click();
  const download = await downloadReady;

  expect(download.suggestedFilename()).toBe("sophia-financas-20261012.json");
  await expect(page.getByRole("status")).toContainText(
    "Cópia dos seus dados financeiros baixada.",
  );
});

test("o proprietário pode reconfigurar o autenticador com QR temporário", async ({ page }) => {
  const state = await mockFinanceApi(page, { owner: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Minha conta de Pessoa de teste" }).click();
  await page.getByRole("button", { name: "Trocar autenticador" }).click();

  await page.getByLabel("Senha atual", { exact: true }).fill("uma-senha-segura-para-teste");
  await page.getByLabel("Código atual do Authy").fill("123456");
  await page.getByRole("button", { name: "Gerar novo QR" }).click();
  await expect(page.getByRole("img", { name: "QR code para configurar o novo autenticador da SophIA" })).toBeVisible();
  await page.getByText("Precisa inserir manualmente?").click();
  await expect(page.locator(".mfa-enrollment-qr-panel code")).toHaveText("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP");

  await page.getByLabel("Código do novo autenticador").fill("654321");
  await page.getByRole("button", { name: "Confirmar novo autenticador" }).click();
  await expect(page.getByRole("heading", { name: "Entre na sua conta" })).toBeVisible();
  expect(state.mfaRotationStartRequests).toBe(1);
  expect(state.mfaRotationConfirmRequests).toBe(1);
});

test("a importação de CSV só grava depois da revisão de duplicidades e confirmação explícita", async ({
  page,
}) => {
  const state = await mockFinanceApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Lançamentos", exact: true }).click();
  const chooseCsv = page.getByRole("button", { name: "Escolher CSV" });
  const csvButtonAlignment = await chooseCsv.evaluate((element) => {
    const style = getComputedStyle(element);
    return { alignItems: style.alignItems, justifyContent: style.justifyContent, textAlign: style.textAlign };
  });
  expect(csvButtonAlignment).toEqual({ alignItems: "center", justifyContent: "center", textAlign: "center" });
  await page.getByLabel("Arquivo CSV").setInputFiles({
    name: "lancamentos.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      "data;descricao;tipo;valor;conta;categoria\n10/10/2026;Compra nova;despesa;45,90;Conta de teste;Alimentação\n",
    ),
  });
  await page.getByRole("button", { name: "Analisar arquivo" }).click();

  await expect(page.getByText("Possível duplicidade")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Confirmar 1 lançamento" }),
  ).toBeDisabled();
  expect(state.importPreviewRequests).toBe(1);
  expect(state.importConfirmRequests).toHaveLength(0);

  await page.getByLabel("Decisão para linha 3").selectOption("SKIP");
  await page.getByLabel(/Revisei as linhas/).check();
  await page.getByRole("button", { name: "Confirmar 1 lançamento" }).click();
  await expect(page.locator(".workspace-notice")).toContainText(
    "1 lançamento importado; 1 linha ignorada",
  );
  expect(state.importConfirmRequests).toEqual([
    { confirmed: true, decisions: [{ row_number: 3, action: "SKIP" }] },
  ]);
});

test("a prévia de um CSV grande pagina e preserva a confirmação", async ({ page }) => {
  const state = await mockFinanceApi(page, { largeLists: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Lançamentos", exact: true }).click();
  await page.getByLabel("Arquivo CSV").setInputFiles({
    name: "lancamentos-grandes.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("data;descricao;tipo;valor;conta;categoria\n10/10/2026;Compra;despesa;45,90;Conta de teste;Alimentação\n"),
  });
  await page.getByRole("button", { name: "Analisar arquivo" }).click();

  const preview = page.locator(".transaction-import-review");
  await expect(preview.locator(".transaction-import-row")).toHaveCount(15);
  await preview.getByRole("navigation", { name: "Paginação das linhas importadas" }).getByRole("button", { name: "Próxima" }).click();
  await expect(preview.locator(".transaction-import-row")).toHaveCount(6);
  await page.getByLabel(/Revisei as linhas/).check();
  await page.getByRole("button", { name: "Confirmar 21 lançamentos" }).click();
  expect(state.importConfirmRequests).toEqual([{ confirmed: true, decisions: [] }]);
});

for (const mode of [
  { name: "desktop", viewport: { width: 1440, height: 960 }, isMobile: false },
  { name: "celular", viewport: { width: 390, height: 844 }, isMobile: true },
]) {
  test(`os formulários de Programados aparecem imediatamente após abrir em ${mode.name}`, async ({
    browser,
  }) => {
    const context = await browser.newContext({
      viewport: mode.viewport,
      isMobile: mode.isMobile,
      hasTouch: mode.isMobile,
      reducedMotion: "reduce",
      timezoneId: "America/Sao_Paulo",
    });
    const page = await context.newPage();
    await page.clock.install({ time: new Date("2026-10-12T12:00:00-03:00") });
    await mockFinanceApi(page);
    await page.goto("/");

    if (mode.isMobile) {
      await page.getByRole("button", { name: "Abrir menu de navegação" }).click();
      await expect(page.getByRole("button", { name: "Fechar menu" })).toBeVisible();
    }
    await page.getByRole("button", { name: "Programados", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Programados", exact: true })).toBeVisible();

    const assertFormAtTop = async (headingName: string) => {
      const heading = page.getByRole("heading", { name: headingName, exact: true });
      await expect(heading).toBeInViewport();
      await expect.poll(async () => (await heading.boundingBox())?.y ?? Number.POSITIVE_INFINITY)
        .toBeGreaterThanOrEqual(0);
      await expect.poll(async () => (await heading.boundingBox())?.y ?? Number.POSITIVE_INFINITY)
        .toBeLessThan(160);

      const form = page.locator("form.recurrence-form").filter({ has: heading });
      const cancelButton = form.getByRole("button", { name: "Cancelar", exact: true });
      const centerOffset = await cancelButton.evaluate((button) => {
        const range = document.createRange();
        range.selectNodeContents(button);
        const text = range.getBoundingClientRect();
        const box = button.getBoundingClientRect();
        return Math.abs(text.left + text.width / 2 - (box.left + box.width / 2));
      });
      expect(centerOffset).toBeLessThan(3);
      await cancelButton.click();
    };

    const newRuleButton = page.getByRole("button", { name: "Nova recorrência", exact: true });
    await newRuleButton.evaluate((element) => {
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        if (parent.scrollHeight > parent.clientHeight) parent.scrollTop = parent.scrollHeight;
      }
      window.scrollTo(0, document.documentElement.scrollHeight);
    });
    await newRuleButton.click();
    await assertFormAtTop("Nova recorrência");

    const newCommitmentButton = page.getByRole("button", { name: "Novo compromisso", exact: true });
    await newCommitmentButton.evaluate((element) => {
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        if (parent.scrollHeight > parent.clientHeight) parent.scrollTop = parent.scrollHeight;
      }
      window.scrollTo(0, document.documentElement.scrollHeight);
    });
    await newCommitmentButton.click();
    await assertFormAtTop("Novo pagamento previsto");
    await context.close();
  });
}

test("listas longas de finanças e cartões mostram 15 itens e avançam por página", async ({ page }) => {
  await mockFinanceApi(page, { largeLists: true });
  await page.goto("/");

  await page.getByRole("button", { name: "Contas", exact: true }).click();
  await expect(page.locator(".data-table tbody tr")).toHaveCount(15);
  await page.getByRole("navigation", { name: "Paginação das contas" }).getByRole("button", { name: "Próxima" }).click();
  await expect(page.locator(".data-table tbody tr")).toHaveCount(6);

  await page.getByRole("button", { name: "Cartões", exact: true }).click();
  const upcoming = page.getByRole("region", { name: "Próximas faturas de todos os cartões" });
  await expect(upcoming.locator(".upcoming-invoice-row")).toHaveCount(15);
  await upcoming.getByRole("navigation", { name: "Paginação das próximas faturas" }).getByRole("button", { name: "Próxima" }).click();
  await expect(upcoming.locator(".upcoming-invoice-row")).toHaveCount(6);

  await page.getByLabel("Cartão para visualizar").selectOption({ label: "Cartão 1" });
  const invoiceCycles = page.locator("#card-invoice-cycles .data-table tbody tr");
  await expect(invoiceCycles).toHaveCount(15);
  await page.getByRole("navigation", { name: "Paginação das faturas do cartão" }).getByRole("button", { name: "Próxima" }).click();
  await expect(invoiceCycles).toHaveCount(6);

  await expect(page.getByRole("navigation", { name: "Paginação dos cartões" })).toBeVisible();
  await page.getByRole("navigation", { name: "Paginação dos cartões" }).getByRole("button", { name: "Próxima" }).click();
  await expect(page.locator(".card-workspace > section.surface-card").first().locator(".data-table tbody tr")).toHaveCount(6);
});

test("categorias abrem os lançamentos e preservam o filtro ao avançar e voltar por cursor", async ({ page }) => {
  const state = await mockFinanceApi(page, { largeLists: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Categorias", exact: true }).click();

  await page.getByRole("button", { name: "Ver lançamentos da categoria Categoria 4" }).click();
  await expect(page.getByRole("heading", { name: "Lançamentos · Categoria 4", exact: true })).toBeVisible();
  await expect(page.locator(".filter-form select").nth(1)).toHaveValue("synthetic-category-4");
  await expect(page.locator(".transaction-table tbody tr")).toHaveCount(15);
  await page.getByRole("navigation", { name: "Paginação dos lançamentos" }).getByRole("button", { name: "Próxima" }).click();
  await expect(page.locator(".transaction-table tbody tr")).toHaveCount(6);
  await page.getByRole("navigation", { name: "Paginação dos lançamentos" }).getByRole("button", { name: "Anterior" }).click();
  await expect(page.locator(".transaction-table tbody tr")).toHaveCount(15);

  const categoryQueries = state.transactionQueries
    .map((query) => new URLSearchParams(query))
    .filter((query) => query.get("category_id") === "synthetic-category-4");
  expect(categoryQueries).toHaveLength(3);
  expect(categoryQueries[0].get("cursor")).toBeNull();
  expect(categoryQueries[1].get("cursor")).toBe("15");
  expect(categoryQueries[2].get("cursor")).toBeNull();
});

test("categorias no resumo e em qualquer célula da linha abrem seus lançamentos", async ({ page }) => {
  await mockFinanceApi(page, { categoryBreakdown: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Visão geral", exact: true }).click();

  await page.getByRole("button", { name: "Ver lançamentos da categoria Alimentação" }).click();
  await expect(page.getByRole("heading", { name: "Lançamentos · Alimentação", exact: true })).toBeVisible();
  await expect(page.locator(".transaction-table tbody tr")).toContainText("Abastecimento de teste");
  await expect(page.locator(".filter-form input").nth(0)).toHaveValue("01/10/2026");
  await expect(page.locator(".filter-form input").nth(1)).toHaveValue("31/10/2026");

  await page.getByRole("button", { name: "Categorias", exact: true }).click();
  const categoryRow = page.getByRole("region", { name: "Categorias de despesas" }).locator("tbody tr").filter({ hasText: "Alimentação" });
  await expect(categoryRow.getByRole("button", { name: "Ver lançamentos da categoria Alimentação" })).toBeVisible();
  await expect(categoryRow.getByRole("button", { name: "Ver lançamentos", exact: true })).toHaveCount(0);
  await categoryRow.locator("td").nth(1).click();
  await expect(page.getByRole("heading", { name: "Lançamentos · Alimentação", exact: true })).toBeVisible();
});

test("editar leva ao formulário e as situações das categorias ficam alinhadas", async ({ page }) => {
  await mockFinanceApi(page, { largeLists: true });
  await page.goto("/");

  const expectEditorVisible = async (name: string) => {
    const heading = page.getByRole("heading", { name, exact: true });
    await expect(heading).toBeInViewport();
    await expect(heading).toBeFocused();
    await expect.poll(async () => (await heading.boundingBox())?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(160);
  };

  await page.getByRole("button", { name: "Categorias", exact: true }).click();
  const incomeTable = page.locator(".category-group-income .category-table");
  const expenseTable = page.locator(".category-group-expense .category-table");
  const incomeStatusX = await incomeTable.locator("tbody tr").first().locator("td").nth(1).evaluate((cell) => cell.getBoundingClientRect().x);
  const expenseStatusX = await expenseTable.locator("tbody tr").first().locator("td").nth(1).evaluate((cell) => cell.getBoundingClientRect().x);
  expect(Math.abs(incomeStatusX - expenseStatusX)).toBeLessThan(1);

  await expenseTable.locator("tbody tr").filter({ hasText: "Categoria 18" }).getByRole("button", { name: "Editar" }).click();
  await expectEditorVisible("Editar categoria");

  await page.getByRole("button", { name: "Contas", exact: true }).click();
  await page.locator(".data-table tbody tr").filter({ hasText: "Conta 15" }).getByRole("button", { name: "Editar" }).click();
  await expectEditorVisible("Editar conta");

  await page.getByRole("button", { name: "Lançamentos", exact: true }).click();
  await page.locator(".transaction-table tbody tr").filter({ hasText: "Lançamento 15" }).getByRole("button", { name: "Editar" }).click();
  await expectEditorVisible("Editar lançamento");

  await page.getByRole("button", { name: "Cartões", exact: true }).click();
  await page.locator(".card-workspace > section.surface-card").first().locator(".data-table tbody tr").filter({ hasText: "Cartão 15" }).getByRole("button", { name: "Editar" }).click();
  await expectEditorVisible("Editar cartão");

  await page.getByRole("button", { name: "Programados", exact: true }).click();
  await page.locator(".recurrence-rule-row").filter({ hasText: "Regra 15" }).getByRole("button", { name: "Editar Regra 15" }).click();
  await expectEditorVisible("Editar recorrência");

  const commitment = page.locator(".recurrence-occurrences-card").first().locator(".recurrence-occurrence-row").filter({ hasText: "Pagamento previsto 15" });
  await commitment.getByRole("button", { name: "Editar Pagamento previsto 15" }).click();
  await expectEditorVisible("Editar pagamento previsto");

  const occurrence = page.locator(".recurrence-occurrences-card").nth(1).locator(".recurrence-occurrence-row").filter({ hasText: "Ocorrência 15" });
  await occurrence.getByRole("button", { name: "Editar", exact: true }).click();
  await expectEditorVisible("Editar ocorrência");
});

test("clicar em um cartão no resumo abre os ciclos desse cartão", async ({ page }) => {
  await mockFinanceApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Visão geral", exact: true }).click();

  await page.getByRole("button", { name: "Abrir faturas do cartão Gold" }).click();
  await expect(page.getByLabel("Cartão para visualizar")).toHaveValue("synthetic-card-gold");
  await expect(page.getByRole("heading", { name: "Faturas de Gold", exact: true })).toBeInViewport();
});

test("regras, compromissos e ocorrências usam paginação no lugar de mostrar histórico", async ({ page }) => {
  await mockFinanceApi(page, { largeLists: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Programados", exact: true }).click();

  await expect(page.locator(".recurrence-rule-row")).toHaveCount(15);
  await page.getByRole("navigation", { name: "Paginação das regras programadas" }).getByRole("button", { name: "Próxima" }).click();
  await expect(page.locator(".recurrence-rule-row")).toHaveCount(6);

  const commitments = page.locator(".recurrence-occurrences-card").first();
  await expect(commitments.locator(".recurrence-occurrence-row")).toHaveCount(15);
  await commitments.getByRole("navigation", { name: "Paginação dos pagamentos previstos" }).getByRole("button", { name: "Próxima" }).click();
  await expect(commitments.locator(".recurrence-occurrence-row")).toHaveCount(6);

  await expect(page.getByRole("button", { name: "Mostrar histórico" })).toHaveCount(0);
  const occurrences = page.locator(".recurrence-occurrences-card").nth(1);
  await occurrences.getByRole("navigation", { name: "Paginação das ocorrências programadas" }).getByRole("button", { name: "Próxima" }).click();
  await expect(occurrences.locator(".recurrence-occurrence-row")).toHaveCount(6);
});

test("o proprietário pode criar e excluir contas de acesso sem dados", async ({ page }) => {
  await mockFinanceApi(page, { owner: true, managedUserEnrolled: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Preferências", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Contas de acesso" })).toBeVisible();
  await page.getByLabel("Nome da pessoa").fill("Richard");
  await page.getByLabel("E-mail de acesso").fill("richard@example.com");
  await page.getByLabel("Senha inicial").fill("senha-sintetica-segura-123");
  await page.getByRole("button", { name: "Criar conta" }).click();
  await expect(page.getByRole("status")).toContainText("Conta de Richard criada");
  await expect(page.getByText("richard@example.com")).toBeVisible();
  await expect(page.getByText("Autenticador pendente").first()).toBeVisible();

  const enrolledUser = page.locator(".settings-managed-user-row").filter({ hasText: "mfa@example.com" });
  await enrolledUser.getByRole("button", { name: "Redefinir MFA" }).click();
  await enrolledUser.getByLabel("Sua senha").fill("senha-sintetica-segura-123");
  await enrolledUser.getByLabel("Seu código MFA").fill("123456");
  await enrolledUser.getByRole("button", { name: "Confirmar redefinição" }).click();
  await expect(page.getByRole("status")).toContainText("O autenticador de Conta com MFA foi redefinido");

  await page.getByRole("button", { name: "Excluir acesso de Richard" }).click();
  await page.getByRole("button", { name: "Confirmar exclusão de Richard" }).click();
  await expect(page.getByRole("status")).toContainText("O acesso de Richard foi excluído");
  await expect(page.getByText("richard@example.com")).toHaveCount(0);
});

test("o histórico mostra 10 conversas e carrega mais ao rolar até o fim", async ({ page }) => {
  await mockFinanceApi(page, { largeLists: true });
  await page.goto("/");

  const history = page.locator(".assistant-history");
  await expect(history.locator(".history-row")).toHaveCount(10);
  await expect(history.locator('[aria-live="polite"]')).toHaveText("Histórico: 10 de 32 conversas exibidas.");
  await history.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  await expect(history.locator(".history-row")).toHaveCount(20);
  await expect(history.locator('[aria-live="polite"]')).toHaveText("Histórico: 20 de 32 conversas exibidas.");
  await history.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  await expect(history.locator(".history-row")).toHaveCount(30);
  await expect(history.locator('[aria-live="polite"]')).toHaveText("Histórico: 30 de 32 conversas exibidas.");
  await history.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  await expect(history.locator(".history-row")).toHaveCount(32);
  await expect(history.locator('[aria-live="polite"]')).toHaveText("Histórico: 32 de 32 conversas exibidas.");
});

for (const width of [390, 820]) {
  test(`o resumo e os avisos permanecem legíveis em uma tela de ${width}px`, async ({
    browser,
  }) => {
    const context = await browser.newContext({
      viewport: { width, height: 844 },
      isMobile: width <= 760,
      hasTouch: width <= 760,
      timezoneId: "America/Sao_Paulo",
    });
    const page = await context.newPage();
    await page.clock.install({ time: new Date("2026-10-12T12:00:00-03:00") });
    await mockFinanceApi(page);
    await page.goto("/");

    if (width <= 1120)
      await expect(
        page.locator(".assistant-context-panel.mobile-open"),
      ).toHaveCount(0);
    const alerts = page.locator(".assistant-notifications-toggle");
    const icon = alerts.locator("svg");
    const count = alerts.locator(".notification-count");
    await expect(count).toHaveText("1");
    const [iconBox, countBox] = await Promise.all([
      icon.boundingBox(),
      count.boundingBox(),
    ]);
    if (!iconBox || !countBox)
      throw new Error("O ícone ou o contador de avisos não está visível.");
    expect(iconBox.x + iconBox.width).toBeLessThanOrEqual(countBox.x);

    await page
      .getByRole("textbox", { name: "Mensagem para o assistente" })
      .fill("Quanto gastei neste mês?");
    await page.getByRole("button", { name: "Enviar mensagem" }).click();
    const summary = page.locator(".summary-result .assistant-summary-values");
    await expect(summary).toBeVisible();
    const columns = await summary.evaluate(
      (element) =>
        getComputedStyle(element).gridTemplateColumns.trim().split(/\s+/)
          .length,
    );
    expect(columns).toBe(1);

    for (const row of await summary.locator(":scope > div").all()) {
      const label = await row.locator("span").boundingBox();
      const amount = await row.locator("strong").boundingBox();
      if (!label || !amount)
        throw new Error("O rótulo ou o valor do resumo não está visível.");
      expect(label.x + label.width).toBeLessThanOrEqual(amount.x);
    }
    await context.close();
  });
}

for (const mode of [
  { name: "desktop", viewport: { width: 1440, height: 960 }, isMobile: false },
  { name: "mobile", viewport: { width: 390, height: 844 }, isMobile: true },
]) {
  test(`a lista consolidada de faturas aparece por vencimento mais próximo em ${mode.name}`, async ({
    browser,
  }) => {
    const context = await browser.newContext({
      viewport: mode.viewport,
      isMobile: mode.isMobile,
      hasTouch: mode.isMobile,
      timezoneId: "America/Sao_Paulo",
    });
    const page = await context.newPage();
    await page.clock.install({ time: new Date("2026-10-12T12:00:00-03:00") });
    await mockFinanceApi(page);
    await page.goto("/");

    if (mode.isMobile) {
      await page
        .getByRole("button", { name: "Abrir menu de navegação" })
        .click();
      await expect(
        page.getByRole("button", { name: "Fechar menu" }),
      ).toBeVisible();
    }
    await page.getByRole("button", { name: "Cartões", exact: true }).click();

    const invoiceRegion = page.getByRole("region", {
      name: "Próximas faturas de todos os cartões",
    });
    await expect(invoiceRegion).toBeVisible();
    const invoiceRows = invoiceRegion.locator(".upcoming-invoice-row");
    await expect(invoiceRows).toHaveCount(3);
    const orderedCards = await invoiceRegion
      .locator(".upcoming-invoice-card strong")
      .allTextContents();
    expect(orderedCards).toEqual(["Inter", "Nubank", "Gold"]);
    await expect(invoiceRows.first()).toContainText("15/10/2026");

    const cycleCard = page.getByLabel("Cartão para visualizar");
    await cycleCard.selectOption({ label: "Gold" });
    await expect(cycleCard).toHaveValue("synthetic-card-gold");
    await expect(
      page.getByRole("heading", { name: "Faturas de Gold", exact: true }),
    ).toBeVisible();

    if (mode.isMobile) {
      const dimensions = await page.evaluate(() => ({
        viewportWidth: document.documentElement.clientWidth,
        documentWidth: document.documentElement.scrollWidth,
        invoiceWidth:
          document.querySelector(".upcoming-invoices")?.getBoundingClientRect()
            .width ?? 0,
      }));
      expect(dimensions.documentWidth).toBeLessThanOrEqual(
        dimensions.viewportWidth,
      );
      expect(dimensions.invoiceWidth).toBeGreaterThan(0);
      expect(dimensions.invoiceWidth).toBeLessThanOrEqual(
        dimensions.viewportWidth,
      );
    }
    await context.close();
  });
}
