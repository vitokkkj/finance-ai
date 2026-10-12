import { expect, test } from "@playwright/test";

import { mockFinanceApi } from "./api-mocks";

test.beforeEach(async ({ page }) => {
  await page.clock.install({ time: new Date("2026-10-12T12:00:00-03:00") });
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

test("categorias abrem os lançamentos correspondentes e mantêm paginação", async ({ page }) => {
  await mockFinanceApi(page, { largeLists: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Categorias", exact: true }).click();

  await page.getByRole("button", { name: "Ver lançamentos da categoria Categoria 4" }).click();
  await expect(page.getByRole("heading", { name: "Lançamentos · Categoria 4", exact: true })).toBeVisible();
  await expect(page.locator(".filter-form select").nth(1)).toHaveValue("synthetic-category-4");
  await expect(page.locator(".transaction-table tbody tr")).toHaveCount(15);
  await page.getByRole("navigation", { name: "Paginação dos lançamentos" }).getByRole("button", { name: "Próxima" }).click();
  await expect(page.locator(".transaction-table tbody tr")).toHaveCount(6);
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

test("clicar em um cartão no resumo abre os ciclos desse cartão", async ({ page }) => {
  await mockFinanceApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Visão geral", exact: true }).click();

  await page.getByRole("button", { name: "Abrir faturas do cartão Gold" }).click();
  await expect(page.getByLabel("Cartão para visualizar")).toHaveValue("synthetic-card-gold");
  await expect(page.getByRole("heading", { name: "Faturas de Gold", exact: true })).toBeInViewport();
});

for (const width of [390, 820, 1440]) {
  test(`formulário de criação de conta se alinha ao espaço disponível em ${width}px`, async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      isMobile: width <= 760,
      hasTouch: width <= 760,
    });
    const page = await context.newPage();
    await mockFinanceApi(page, { owner: true });
    await page.goto("/");
    if (width <= 760) await page.getByRole("button", { name: "Abrir menu de navegação" }).click();
    await page.getByRole("button", { name: "Preferências", exact: true }).click();

    const form = page.locator(".settings-managed-user-form");
    const columns = await form.evaluate((element) => getComputedStyle(element).gridTemplateColumns.trim().split(/\s+/).length);
    expect(columns).toBe(width === 390 ? 1 : 2);
    const pageDimensions = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth, content: document.documentElement.scrollWidth }));
    expect(pageDimensions.content).toBeLessThanOrEqual(pageDimensions.viewport);
    await context.close();
  });
}

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

test("somente a conta proprietária vê a área de criação de acessos", async ({ page }) => {
  await mockFinanceApi(page, { owner: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Preferências", exact: true }).click();

  await page.getByLabel("Nome da pessoa").fill("Colega de teste");
  await page.getByLabel("E-mail de acesso").fill("colega@example.com");
  await page.getByLabel("Senha inicial").fill("senha-inicial-segura-123");
  await page.getByRole("button", { name: "Criar conta" }).click();
  await expect(page.getByRole("status")).toContainText("Conta de Colega criada");
  await expect(page.locator(".settings-managed-user-list")).toContainText("colega@example.com");
});

test("o histórico de conversas mostra 15 itens por página", async ({ page }) => {
  await mockFinanceApi(page, { largeLists: true });
  await page.goto("/");

  const history = page.locator(".assistant-history");
  await expect(history.locator(".history-row")).toHaveCount(15);
  await history.getByRole("navigation", { name: "Paginação das conversas" }).getByRole("button", { name: "Próxima" }).click();
  await expect(history.locator(".history-row")).toHaveCount(6);
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
