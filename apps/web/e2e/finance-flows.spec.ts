import { expect, test, type Locator } from "@playwright/test";

import { mockFinanceApi } from "./api-mocks";

async function loadNextHistoryBatch(history: Locator, input: "wheel" | "touch") {
  const scrollable = await history.evaluate((element) => element.scrollHeight - element.clientHeight > 1);
  if (scrollable) {
    await history.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
      element.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    return;
  }

  if (input === "wheel") {
    await history.evaluate((element) => {
      element.dispatchEvent(new WheelEvent("wheel", { deltaY: 120, bubbles: true, cancelable: true }));
    });
    return;
  }

  await history.evaluate((element) => {
    const start = new Touch({ identifier: 1, target: element, clientX: 40, clientY: 180 });
    const end = new Touch({ identifier: 1, target: element, clientX: 40, clientY: 140 });
    element.dispatchEvent(new TouchEvent("touchstart", { bubbles: true, touches: [start], changedTouches: [start] }));
    element.dispatchEvent(new TouchEvent("touchend", { bubbles: true, touches: [], changedTouches: [end] }));
  });
}

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
  const selects = filters.locator("select");
  await expect(selects).toHaveCount(3);
  for (const select of await selects.all()) {
    await expect(select).toHaveCSS("background-repeat", "no-repeat");
    await expect(select).toHaveCSS("background-size", "14px auto");
    await expect(select).toHaveCSS("appearance", "none");
    expect(await select.evaluate((element) => getComputedStyle(element).backgroundImage)).toContain(
      "data:image/svg+xml",
    );
  }
  await filters.getByLabel("Tipo").selectOption("EXPENSE");
  await filters.getByRole("button", { name: "Filtrar" }).click();

  const summary = page.getByRole("region", { name: "Resumo dos lançamentos filtrados" });
  await expect(summary).toContainText("24 lançamentos correspondentes, em todas as páginas");
  await expect(summary).toContainText("Despesas");
  await expect(summary).toContainText("R$ 288,00");
  expect(state.transactionQueries.some((query) => query.includes("type=EXPENSE"))).toBe(true);
});

test("o chat mostra ganhos por dia e desdobra cards de lançamentos aninhados", async ({ page }) => {
  await mockFinanceApi(page);
  const structuredItem = {
    type: "transaction_card",
    data: {
      data: {
        items: [
          {
            id: "earning-20261006",
            type: "INCOME",
            description: "Salário Entregas",
            amount: "70.00",
            occurred_at: "2026-10-06",
            category_name: "Entregas",
          },
        ],
        summary: {
          transaction_count: 3,
          income_total: "170.00",
          expense_total: "0.00",
          card_purchase_total: "0.00",
          expenses_total: "0.00",
          transfer_total: "0.00",
          card_payment_total: "0.00",
          result_total: "170.00",
          daily_totals: [
            {
              occurred_on: "2026-10-05",
              income_total: "100.00",
              expenses_total: "0.00",
              transfer_total: "0.00",
              card_payment_total: "0.00",
            },
            {
              occurred_on: "2026-10-06",
              income_total: "70.00",
              expenses_total: "0.00",
              transfer_total: "0.00",
              card_payment_total: "0.00",
            },
          ],
        },
      },
    },
  };
  await page.route("**/api/ai/conversations/*/messages", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: `event: text_delta\ndata: ${JSON.stringify({ text: "Você ganhou R$ 170,00 no período." })}\n\nevent: structured\ndata: ${JSON.stringify({ items: [structuredItem] })}\n\nevent: done\ndata: {}\n\n`,
    });
  });
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
        title: "Ganhos por período",
        created_at: "2026-10-12T12:00:00-03:00",
        updated_at: "2026-10-12T12:00:00-03:00",
        messages: [
          { id: "income-question", role: "USER", content: "Quanto ganhei no período?" },
          {
            id: "income-answer",
            role: "ASSISTANT",
            content: "Você ganhou R$ 170,00 no período.",
            structured_content: [structuredItem],
          },
        ],
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Nova conversa" }).click();
  await page.getByRole("textbox", { name: "Mensagem para o assistente" }).fill(
    "Quanto ganhei de entregas de 01/10 a 06/10?",
  );
  await page.getByRole("button", { name: "Enviar mensagem" }).click();

  const card = page.locator(".assistant-data-card").filter({ hasText: "Ganhos por dia" });
  await expect(card).toContainText("R$ 170,00");
  await expect(card.locator(".assistant-transaction-row")).toHaveCount(1);
  expect(await card.textContent()).toContain("Salário Entregas");
  await expect(card.locator(".assistant-daily-row")).toHaveCount(2);
  await expect(card).toContainText("R$ 100,00");
  await expect(card).toContainText("R$ 70,00");
  await expect(card).not.toContainText("Movimento");
});

test("o orbe de pensamento anima e respeita movimento reduzido", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
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

  const orb = page.locator(".assistant-pending-icon");
  await expect(orb).toBeVisible();
  await expect.poll(() => orb.evaluate((element) => {
    const ring = getComputedStyle(element, "::before");
    const core = getComputedStyle(element, "::after");
    return [ring.animationName, ring.animationDuration, core.animationName, core.animationDuration];
  })).toEqual(["sophia-orb-rotate", "1.05s", "sophia-orb-breathe", "1.9s"]);

  const firstRingTransform = await orb.evaluate((element) => getComputedStyle(element, "::before").transform);
  await page.waitForTimeout(180);
  const nextRingTransform = await orb.evaluate((element) => getComputedStyle(element, "::before").transform);
  expect(nextRingTransform).not.toBe(firstRingTransform);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(() => orb.evaluate((element) => [
    getComputedStyle(element, "::before").animationName,
    getComputedStyle(element, "::after").animationName,
    getComputedStyle(element, "i").animationName,
  ])).toEqual(["none", "none", "none"]);

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

test("as telas principais permanecem dentro da viewport em larguras móveis", async ({ browser }) => {
  const routes = [
    "/",
    "/?view=finance&section=overview",
    "/?view=finance&section=transactions",
    "/?view=finance&section=accounts",
    "/?view=finance&section=cards",
    "/?view=finance&section=recurrences",
    "/?view=finance&section=categories",
    "/?view=settings",
  ];

  for (const width of [360, 390, 430]) {
    const context = await browser.newContext({
      viewport: { width, height: 844 },
      isMobile: true,
      hasTouch: true,
      timezoneId: "America/Sao_Paulo",
    });
    const page = await context.newPage();
    await page.clock.install({ time: new Date("2026-10-12T12:00:00-03:00") });
    await mockFinanceApi(page, { largeLists: true });

    for (const route of routes) {
      await page.goto(route);
      if (route === "/") {
        await expect(page.getByRole("textbox", { name: "Mensagem para o assistente" })).toBeVisible();
      } else {
        await expect(page.locator(".workspace-heading h1, .assistant-settings-heading h1").first()).toBeVisible();
      }

      const dimensions = await page.evaluate(() => ({
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: document.documentElement.clientWidth,
        mainRight: document.querySelector(".assistant-main")?.getBoundingClientRect().right ?? 0,
      }));
      expect(dimensions.documentWidth, `${route} excedeu ${width}px`).toBeLessThanOrEqual(dimensions.viewportWidth + 1);
      expect(dimensions.mainRight, `${route} saiu da viewport de ${width}px`).toBeLessThanOrEqual(dimensions.viewportWidth + 1);
    }

    await page.goto("/");
    const composer = page.locator(".assistant-composer");
    const composerBox = await composer.boundingBox();
    if (!composerBox) throw new Error("O compositor do chat não está visível no celular.");
    expect(composerBox.y + composerBox.height).toBeLessThanOrEqual(844 + 1);

    await page.getByRole("button", { name: "Abrir menu de navegação" }).click();
    const drawer = page.locator(".assistant-sidebar.mobile-open");
    await expect(drawer).toBeVisible();
    await expect.poll(async () => (await drawer.boundingBox())?.x ?? Number.NEGATIVE_INFINITY)
      .toBeGreaterThanOrEqual(-1);
    const drawerBox = await drawer.boundingBox();
    if (!drawerBox) throw new Error("O menu móvel não está visível.");
    expect(drawerBox.x).toBeGreaterThanOrEqual(-1);
    expect(drawerBox.y).toBeGreaterThanOrEqual(-1);
    expect(drawerBox.y + drawerBox.height).toBeLessThanOrEqual(844 + 1);

    const firstRows = await drawer.locator(".history-row").evaluateAll((rows) => rows.slice(0, 2).map((row) => {
      const rect = row.getBoundingClientRect();
      return { top: rect.top, bottom: rect.bottom, height: rect.height };
    }));
    if (firstRows.length > 1) {
      expect(firstRows[0].height).toBeLessThanOrEqual(34);
      expect(firstRows[1].top - firstRows[0].bottom).toBeLessThanOrEqual(1);
    }

    const selectedMarker = drawer.locator(".history-row .history-marker").first();
    if (await selectedMarker.count()) {
      const selectedBackground = await selectedMarker.evaluate((element) => {
        element.closest(".history-row")?.classList.add("current");
        return getComputedStyle(element).backgroundColor;
      });
      expect(selectedBackground).toBe("rgba(0, 0, 0, 0)");
    }
    await context.close();
  }
});

test("a mensagem do usuário quebra linha no celular sem sair do chat", async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 360, height: 780 },
    isMobile: true,
    hasTouch: true,
    timezoneId: "America/Sao_Paulo",
  });
  const page = await context.newPage();
  await page.clock.install({ time: new Date("2026-10-12T12:00:00-03:00") });
  await mockFinanceApi(page);
  await page.goto("/");

  const prompt = "Quanto eu ganhei com entregas entre 1 e 25 de outubro deste ano? Mostre os valores organizados por dia.";
  await page.getByRole("textbox", { name: "Mensagem para o assistente" }).fill(prompt);
  await page.getByRole("button", { name: "Enviar mensagem" }).click();

  const bubble = page.locator(".user-message .message-text");
  await expect(bubble).toContainText(prompt);
  const bubbleBox = await bubble.boundingBox();
  const composerBox = await page.locator(".assistant-composer").boundingBox();
  if (!bubbleBox || !composerBox) throw new Error("A mensagem ou o compositor do chat não está visível.");
  expect(bubbleBox.x).toBeGreaterThanOrEqual(0);
  expect(bubbleBox.x + bubbleBox.width).toBeLessThanOrEqual(360 + 1);
  expect(bubbleBox.height).toBeGreaterThan(40);
  expect(composerBox.y + composerBox.height).toBeLessThanOrEqual(780 + 1);
  await expect(page.locator("html")).toHaveJSProperty("scrollWidth", 360);
  await context.close();
});

test("o controle de recolher o menu não quebra o rótulo em desktop", async ({ page }) => {
  await mockFinanceApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const toggle = page.getByRole("button", { name: "Recolher menu lateral" });
  await expect(toggle).toBeVisible();
  const label = toggle.locator("span");
  const labelBox = await label.boundingBox();
  if (!labelBox) throw new Error("O rótulo do menu lateral não está visível.");
  expect(labelBox.height).toBeLessThanOrEqual(16);
  expect(await toggle.evaluate((element) => getComputedStyle(element).width)).not.toBe("34px");
  await page.getByRole("button", { name: "Recolher menu lateral" }).click();
  await expect(page.locator(".assistant-layout")).toHaveClass(/sidebar-collapsed/);
  await page.getByRole("button", { name: "Expandir menu lateral" }).click();
  await expect(page.locator(".assistant-layout")).not.toHaveClass(/sidebar-collapsed/);
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
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute("content", "#f2f6f3");
  await page.getByRole("button", { name: "Ativar tema escuro" }).click();
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute("content", "#141c16");
  await page.getByRole("button", { name: "Ativar tema claro" }).click();
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute("content", "#f2f6f3");
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

test("o histórico preenche o espaço livre e carrega mais 10 ao rolar até o fim", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1400 });
  await mockFinanceApi(page, { largeLists: true });
  await page.goto("/");

  const history = page.locator(".assistant-history");
  await expect.poll(() => history.locator(".history-row").count()).toBeGreaterThan(10);
  const initialCount = await history.locator(".history-row").count();
  expect(initialCount).toBeLessThan(32);
  await expect(history.locator('[aria-live="polite"]')).toHaveText(`Histórico: ${initialCount} de 32 conversas exibidas.`);
  const historyAndNavigationGap = await page.evaluate(() => {
    const historyElement = document.querySelector(".assistant-history");
    const navigationElement = document.querySelector(".assistant-nav");
    if (!historyElement || !navigationElement) return Number.POSITIVE_INFINITY;
    return navigationElement.getBoundingClientRect().top - historyElement.getBoundingClientRect().bottom;
  });
  expect(historyAndNavigationGap).toBeLessThanOrEqual(2);
  await loadNextHistoryBatch(history, "wheel");
  const afterFirstLoad = Math.min(initialCount + 10, 32);
  await expect(history.locator(".history-row")).toHaveCount(afterFirstLoad);
  await expect(history.locator('[aria-live="polite"]')).toHaveText(`Histórico: ${afterFirstLoad} de 32 conversas exibidas.`);
  await loadNextHistoryBatch(history, "wheel");
  const afterSecondLoad = Math.min(afterFirstLoad + 10, 32);
  await expect(history.locator(".history-row")).toHaveCount(afterSecondLoad);
  await expect(history.locator('[aria-live="polite"]')).toHaveText(`Histórico: ${afterSecondLoad} de 32 conversas exibidas.`);
  await loadNextHistoryBatch(history, "wheel");
  await expect(history.locator(".history-row")).toHaveCount(32);
  await expect(history.locator('[aria-live="polite"]')).toHaveText("Histórico: 32 de 32 conversas exibidas.");
});

test("o histórico mobile rola no próprio menu e carrega mais conversas automaticamente", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 1000 });
  await mockFinanceApi(page, { largeLists: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Abrir menu de navegação" }).click();

  const history = page.locator(".assistant-sidebar.mobile-open .assistant-history");
  await expect.poll(() => history.locator(".history-row").count()).toBeGreaterThan(10);
  const initialCount = await history.locator(".history-row").count();
  const mobileHistoryAndNavigationGap = await page.evaluate(() => {
    const historyElement = document.querySelector(".assistant-sidebar.mobile-open .assistant-history");
    const navigationElement = document.querySelector(".assistant-sidebar.mobile-open .assistant-nav");
    if (!historyElement || !navigationElement) return Number.POSITIVE_INFINITY;
    return navigationElement.getBoundingClientRect().top - historyElement.getBoundingClientRect().bottom;
  });
  expect(mobileHistoryAndNavigationGap).toBeLessThanOrEqual(2);
  await loadNextHistoryBatch(history, "touch");
  const afterFirstLoad = Math.min(initialCount + 10, 32);
  await expect(history.locator(".history-row")).toHaveCount(afterFirstLoad);
  await expect(history.locator('[aria-live="polite"]')).toHaveText(`Histórico: ${afterFirstLoad} de 32 conversas exibidas.`);

  if (afterFirstLoad < 32) {
    await loadNextHistoryBatch(history, "touch");
    await expect(history.locator(".history-row")).toHaveCount(Math.min(afterFirstLoad + 10, 32));
  }
});

test("resumo inicial tem respiro interno e ícones das sugestões centralizados", async ({ page }) => {
  await mockFinanceApi(page);
  await page.goto("/");

  const summary = page.locator(".assistant-home-summary");
  await expect(summary).toBeVisible();
  const horizontalPadding = await summary.evaluate((element) => Number.parseFloat(getComputedStyle(element).paddingLeft));
  expect(horizontalPadding).toBeGreaterThanOrEqual(14);

  const icon = page.locator(".assistant-suggestions .suggestion-index").first();
  await expect(icon).toBeVisible();
  const alignment = await icon.evaluate((element) => {
    const iconBox = element.getBoundingClientRect();
    const svg = element.querySelector("svg")?.getBoundingClientRect();
    return {
      display: getComputedStyle(element).display,
      horizontalOffset: svg ? Math.abs((iconBox.left + iconBox.width / 2) - (svg.left + svg.width / 2)) : Number.POSITIVE_INFINITY,
      verticalOffset: svg ? Math.abs((iconBox.top + iconBox.height / 2) - (svg.top + svg.height / 2)) : Number.POSITIVE_INFINITY,
    };
  });
  expect(alignment.display).toBe("grid");
  expect(alignment.horizontalOffset).toBeLessThanOrEqual(1);
  expect(alignment.verticalOffset).toBeLessThanOrEqual(1);
});

test("conversas antigas mantêm acesso ao contexto financeiro", async ({ page }) => {
  await mockFinanceApi(page, { largeLists: true });
  await page.route("**/api/ai/conversations/synthetic-conversation-1", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "synthetic-conversation-1",
        title: "8,98 em Farmácia",
        created_at: "2026-10-12T12:00:00-03:00",
        updated_at: "2026-10-12T12:00:00-03:00",
        messages: [
          { id: "old-user-message", role: "USER", content: "8,98 em Farmácia" },
          { id: "old-assistant-message", role: "ASSISTANT", content: "Registrei a despesa de R$ 8,98 em Farmácia." },
        ],
      }),
    });
  });
  await page.goto("/");

  await page.getByRole("button", { name: "Conversa de teste 1", exact: true }).click();
  await expect(page.getByText("Registrei a despesa de R$ 8,98 em Farmácia.")).toBeVisible();
  const contextToggle = page.getByRole("button", { name: "Abrir contexto financeiro" });
  await expect(contextToggle).toBeVisible();
  await contextToggle.click();
  const contextPanel = page.getByRole("complementary", { name: "Contexto financeiro" });
  await expect(contextPanel).toContainText("Saldos por conta");
  await expect.poll(() => contextPanel.evaluate((element) => Number.parseFloat(getComputedStyle(element).gap))).toBeGreaterThanOrEqual(12);
  await expect.poll(() => contextPanel.evaluate((element) => element.getBoundingClientRect().width)).toBeGreaterThanOrEqual(360);
  await expect(contextPanel.locator(".context-metrics strong").first()).toHaveCSS("font-size", "14px");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Abrir contexto financeiro" })).toBeVisible();
  await page.getByRole("button", { name: "Abrir contexto financeiro" }).click();
  await expect(contextPanel).toHaveClass(/mobile-open/);
  await expect(contextPanel).toContainText("Saldos por conta");
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
