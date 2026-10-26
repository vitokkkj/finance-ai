import type { Page, Route } from "@playwright/test";

const BASE_ORIGIN = "http://127.0.0.1:4173";
const CONVERSATION_ID = "synthetic-conversation";
const CARD_IDS = {
  inter: "synthetic-card-inter",
  nubank: "synthetic-card-nubank",
  gold: "synthetic-card-gold",
};

export type E2EApiState = {
  dashboardQueries: string[];
  transactionQueries: string[];
  chatPrompts: string[];
  importPreviewRequests: number;
  mfaRotationStartRequests: number;
  mfaRotationConfirmRequests: number;
  importConfirmRequests: {
    confirmed: boolean;
    decisions: { row_number: number; action: string }[];
  }[];
  cardPurchasePlanRequests: {
    credit_card_id: string;
    category_id: string;
    description: string;
    total_amount: string;
    installment_count: number;
    occurred_at: string;
    notes: string | null;
  }[];
  cardPurchaseRequests: {
    credit_card_id: string;
    category_id: string;
    description: string;
    amount: string;
    occurred_at: string;
    notes: string | null;
  }[];
};

function mockMoneyFromCents(cents: bigint): string {
  const sign = cents < 0n ? "-" : "";
  const absolute = cents < 0n ? -cents : cents;
  return `${sign}${absolute / 100n}.${String(absolute % 100n).padStart(2, "0")}`;
}

function mockSumCents(
  transactions: { amount: string; type: string }[],
  matches: (type: string) => boolean,
): bigint {
  return transactions.reduce((total, transaction) => {
    if (!matches(transaction.type)) return total;
    const isNegative = transaction.amount.startsWith("-");
    const unsigned = isNegative ? transaction.amount.slice(1) : transaction.amount;
    const [units, fraction = "00"] = unsigned.split(".");
    const absolute = BigInt(units) * 100n + BigInt(fraction.padEnd(2, "0").slice(0, 2));
    return total + (isNegative ? -absolute : absolute);
  }, 0n);
}

const cards = [
  {
    id: CARD_IDS.inter,
    name: "Inter",
    institution: "Inter",
    credit_limit: "3000.00",
    closing_day: 5,
    due_day: 15,
    payment_account_id: "synthetic-checking",
    is_active: true,
    used_limit: "120.00",
    available_limit: "2880.00",
    next_due_date: "2026-10-15",
  },
  {
    id: CARD_IDS.nubank,
    name: "Nubank",
    institution: "Nubank",
    credit_limit: "5000.00",
    closing_day: 4,
    due_day: 10,
    payment_account_id: "synthetic-checking",
    is_active: true,
    used_limit: "357.40",
    available_limit: "4642.60",
    next_due_date: "2026-11-10",
  },
  {
    id: CARD_IDS.gold,
    name: "Gold",
    institution: "Banco de teste",
    credit_limit: "2500.00",
    closing_day: 26,
    due_day: 3,
    payment_account_id: "synthetic-checking",
    is_active: true,
    used_limit: "654.63",
    available_limit: "1845.37",
    next_due_date: "2026-12-03",
  },
];

const upcomingInvoices = [
  {
    id: "synthetic-invoice-inter",
    credit_card_id: CARD_IDS.inter,
    credit_card_name: "Inter",
    period_start: "2026-09-06",
    period_end: "2026-10-05",
    due_date: "2026-10-15",
    total: "120.00",
    paid_amount: "0.00",
    outstanding: "120.00",
    status: "OPEN",
  },
  {
    id: "synthetic-invoice-nubank",
    credit_card_id: CARD_IDS.nubank,
    credit_card_name: "Nubank",
    period_start: "2026-10-05",
    period_end: "2026-11-04",
    due_date: "2026-11-10",
    total: "357.40",
    paid_amount: "0.00",
    outstanding: "357.40",
    status: "OPEN",
  },
  {
    id: "synthetic-invoice-gold",
    credit_card_id: CARD_IDS.gold,
    credit_card_name: "Gold",
    period_start: "2026-10-27",
    period_end: "2026-11-26",
    due_date: "2026-12-03",
    total: "654.63",
    paid_amount: "0.00",
    outstanding: "654.63",
    status: "OPEN",
  },
];

const account = {
  id: "synthetic-checking",
  name: "Conta de teste",
  type: "CHECKING",
  currency: "BRL",
  opening_balance: "1500.00",
  opening_balance_date: "2026-10-01",
  is_active: true,
  balance: "1500.00",
};

function dashboardForMonth(year: number, month: number, largeLists = false, categoryBreakdown = false) {
  const periodStart = `${year}-${String(month).padStart(2, "0")}-01`;
  const endDate = new Date(Date.UTC(year, month, 0));
  const periodEnd = `${year}-${String(month).padStart(2, "0")}-${String(endDate.getUTCDate()).padStart(2, "0")}`;
  const futureMonth = year === 2026 && month === 11;
  return {
    as_of: "2026-10-12",
    period_start: periodStart,
    period_end: periodEnd,
    checking_balance: "1500.00",
    incomplete_checking_account_count: 0,
    account_type_balances: [
      {
        account_type: "CHECKING",
        balance: "1500.00",
        projected_balance: futureMonth ? "687.70" : "1500.00",
        account_count: 1,
        incomplete_account_count: 0,
      },
    ],
    monthly_income: "0.00",
    monthly_expenses: "0.00",
    monthly_result: "0.00",
    expenses_by_category: categoryBreakdown
      ? [{ category_id: "synthetic-category-food", category_name: "Alimentação", amount: "195.00" }]
      : [],
    cards: cards.map((card) => ({
      id: card.id,
      name: card.name,
      credit_limit: card.credit_limit,
      used_limit: card.used_limit,
      available_limit: card.available_limit,
      next_due_date: card.next_due_date,
    })),
    recent_transactions: [],
    forecast_start: futureMonth ? periodStart : "2026-10-12",
    forecast_end: futureMonth ? periodEnd : "2026-10-31",
    forecast_payables_total: futureMonth ? "812.30" : "120.00",
    forecast_overdue_total: "0.00",
    forecast_next_7_days_total: futureMonth ? "0.00" : "120.00",
    forecast_rest_of_month_total: futureMonth ? "812.30" : "0.00",
    forecast_income_total: "0.00",
    forecast_unassigned_invoice_total: "0.00",
    forecast_items: largeLists
      ? Array.from({ length: 21 }, (_, index) => ({
          id: `synthetic-forecast-${index + 1}`,
          source: "COMMITMENT",
          credit_card_id: null,
          description: `Compromisso ${index + 1}`,
          type: "EXPENSE",
          due_date: `2026-10-${String(12 + index).padStart(2, "0")}`,
          amount: "20.00",
          account_type: "CHECKING",
          account_name: "Conta de teste",
          card_name: null,
          status: "PLANNED",
        }))
      : futureMonth
      ? [
          {
            id: "synthetic-commitment-november",
            source: "COMMITMENT",
            credit_card_id: null,
            description: "Aluguel previsto em novembro",
            type: "EXPENSE",
            due_date: "2026-11-05",
            amount: "812.30",
            account_type: "CHECKING",
            account_name: "Conta de teste",
            card_name: null,
            status: "PLANNED",
          },
        ]
      : [
          {
            id: "synthetic-commitment-october",
            source: "COMMITMENT",
            credit_card_id: null,
            description: "Conta sintética de outubro",
            type: "EXPENSE",
            due_date: "2026-10-15",
            amount: "120.00",
            account_type: "CHECKING",
            account_name: "Conta de teste",
            card_name: null,
            status: "DUE_SOON",
          },
        ],
  };
}

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

export async function mockFinanceApi(
  page: Page,
  options: { largeLists?: boolean; categoryBreakdown?: boolean; owner?: boolean; managedUserEnrolled?: boolean; failTransactionsRequests?: number; authenticated?: boolean } = {},
): Promise<E2EApiState> {
  const state: E2EApiState = {
    dashboardQueries: [],
    transactionQueries: [],
    chatPrompts: [],
    importPreviewRequests: 0,
    mfaRotationStartRequests: 0,
    mfaRotationConfirmRequests: 0,
    importConfirmRequests: [],
    cardPurchasePlanRequests: [],
    cardPurchaseRequests: [],
  };
  let conversationCreated = false;
  let transactionFailuresRemaining = options.failTransactionsRequests ?? 0;
  let managedUsers = options.owner
    ? [{
        id: "synthetic-owner",
        email: "gamercreeper74@gmail.com",
        display_name: "Proprietário de teste",
        created_at: "2026-10-12T12:00:00-03:00",
        mfa_enrolled: true,
      }, ...(options.managedUserEnrolled ? [{
        id: "synthetic-mfa-user",
        email: "mfa@example.com",
        display_name: "Conta com MFA",
        created_at: "2026-10-11T12:00:00-03:00",
        mfa_enrolled: true,
      }] : [])]
    : [];
  const mockConversations = options.largeLists
    ? Array.from({ length: 32 }, (_, index) => ({
        id: `synthetic-conversation-${index + 1}`,
        title: `Conversa de teste ${index + 1}`,
        created_at: `2026-10-${String(12 - (index % 12)).padStart(2, "0")}T12:00:00-03:00`,
        updated_at: `2026-10-${String(12 - (index % 12)).padStart(2, "0")}T12:00:00-03:00`,
      }))
    : [];
  const mockAccounts = options.largeLists
    ? Array.from({ length: 21 }, (_, index) => ({ ...account, id: `synthetic-account-${index + 1}`, name: `Conta ${index + 1}` }))
    : [account];
  const mockCategories = options.categoryBreakdown
    ? [{ id: "synthetic-category-food", name: "Alimentação", type: "EXPENSE", is_archived: false }]
    : options.largeLists
    ? Array.from({ length: 21 }, (_, index) => ({ id: `synthetic-category-${index + 1}`, name: `Categoria ${index + 1}`, type: index < 3 ? "INCOME" : "EXPENSE", is_archived: false }))
    : [];
  const mockTransactions = options.categoryBreakdown
    ? [{ id: "synthetic-food-transaction", account_id: account.id, category_id: "synthetic-category-food", category_name: "Alimentação", source_account_id: null, destination_account_id: null, invoice_id: null, credit_card_id: null, credit_card_name: null, type: "EXPENSE", source: "MANUAL", status: "CONFIRMED", description: "Abastecimento de teste", amount: "195.00", occurred_at: "2026-10-12", notes: null }]
    : options.largeLists
    ? Array.from({ length: 24 }, (_, index) => ({
        id: `synthetic-transaction-${index + 1}`,
        account_id: account.id,
        category_id: index < 21 ? "synthetic-category-4" : "synthetic-category-5",
        category_name: index < 21 ? "Categoria 4" : "Categoria 5",
        source_account_id: null,
        destination_account_id: null,
        invoice_id: null,
        credit_card_id: null,
        credit_card_name: null,
        type: "EXPENSE",
        source: "MANUAL",
        status: "CONFIRMED",
        description: `Lançamento ${index + 1}`,
        amount: "12.00",
        occurred_at: "2026-10-12",
        notes: null,
      }))
    : [];
  const mockCards = options.largeLists
    ? Array.from({ length: 21 }, (_, index) => ({ ...cards[index % cards.length], id: `synthetic-card-${index + 1}`, name: `Cartão ${index + 1}` }))
    : cards;
  const mockUpcomingInvoices = options.largeLists
    ? Array.from({ length: 21 }, (_, index) => {
        const dueDate = new Date(Date.UTC(2026, 9, 15 + index));
        const card = mockCards[index % mockCards.length];
        return {
          ...upcomingInvoices[index % upcomingInvoices.length],
          id: `synthetic-upcoming-invoice-${index + 1}`,
          credit_card_id: card.id,
          credit_card_name: card.name,
          due_date: dueDate.toISOString().slice(0, 10),
        };
      })
    : upcomingInvoices;
  const mockRules = options.largeLists
    ? Array.from({ length: 21 }, (_, index) => ({
        id: `synthetic-rule-${index + 1}`,
        account_id: account.id,
        category_id: "synthetic-category-4",
        type: "EXPENSE",
        description: `Regra ${index + 1}`,
        amount: "20.00",
        frequency: "MONTHLY",
        interval: 1,
        starts_on: "2026-01-01",
        ends_on: null,
        notes: null,
        is_active: true,
      }))
    : [];
  const mockOccurrences = options.largeLists
    ? Array.from({ length: 21 }, (_, index) => ({
        id: `synthetic-occurrence-${index + 1}`,
        rule_id: `synthetic-rule-${index + 1}`,
        transaction_id: null,
        account_id: account.id,
        category_id: "synthetic-category-4",
        type: "EXPENSE",
        description: `Ocorrência ${index + 1}`,
        amount: "20.00",
        due_date: `2026-10-${String((index % 28) + 1).padStart(2, "0")}`,
        notes: null,
        status: "PLANNED",
      }))
    : [];
  const mockCommitments = options.largeLists
    ? Array.from({ length: 21 }, (_, index) => ({
        id: `synthetic-commitment-${index + 1}`,
        transaction_id: null,
        account_id: account.id,
        category_id: "synthetic-category-4",
        type: "EXPENSE",
        description: `Pagamento previsto ${index + 1}`,
        amount: "20.00",
        due_date: `2026-10-${String((index % 28) + 1).padStart(2, "0")}`,
        notes: null,
        status: "PLANNED",
      }))
    : [];
  const mockInvoices = (cardId: string) => options.largeLists
    ? Array.from({ length: 21 }, (_, index) => {
        const dueDate = new Date(Date.UTC(2026, 9 + index, 3));
        return {
          id: `synthetic-cycle-${cardId}-${index + 1}`,
          credit_card_id: cardId,
          credit_card_name: mockCards.find((card) => card.id === cardId)?.name ?? "Cartão",
          period_start: new Date(Date.UTC(2026, 8 + index, 24)).toISOString().slice(0, 10),
          period_end: new Date(Date.UTC(2026, 9 + index, 23)).toISOString().slice(0, 10),
          closing_date: new Date(Date.UTC(2026, 9 + index, 23)).toISOString().slice(0, 10),
          due_date: dueDate.toISOString().slice(0, 10),
          opening_balance: "0.00",
          total: "20.00",
          paid_amount: "0.00",
          outstanding: "20.00",
          status: "OPEN",
          purchases: [],
          payments: [],
        };
      })
    : [];

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== BASE_ORIGIN) {
      await route.abort("blockedbyclient");
      return;
    }
    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }

    if (url.pathname === "/api/auth/setup-state") {
      await json(route, {
        requires_setup: false,
        setup_available: false,
        bootstrap_token_required: false,
        mfa_required: false,
      });
      return;
    }
    if (url.pathname === "/api/auth/me") {
      if (options.authenticated === false) {
        await route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Sessão necessária." }),
        });
        return;
      }
      await json(route, {
        id: "synthetic-user",
        email: options.owner ? "gamercreeper74@gmail.com" : "teste@example.invalid",
        display_name: "Pessoa de teste",
        mfa_required: Boolean(options.owner),
        mfa_enrolled: Boolean(options.owner),
      });
      return;
    }
    if (url.pathname === "/api/auth/mfa/enrollment/start" && route.request().method() === "POST") {
      state.mfaRotationStartRequests += 1;
      await json(route, {
        qr_code_data_url: "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=",
        manual_key: "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
        expires_at: "2026-10-12T12:10:00-03:00",
      });
      return;
    }
    if (url.pathname === "/api/auth/mfa/enrollment/confirm" && route.request().method() === "POST") {
      state.mfaRotationConfirmRequests += 1;
      await json(route, { mfa_enrolled: true });
      return;
    }
    if (url.pathname === "/api/auth/logout" && route.request().method() === "POST") {
      await json(route, { status: "logged_out" });
      return;
    }
    if (url.pathname === "/api/admin/users" && options.owner) {
      if (route.request().method() === "GET") {
        await json(route, managedUsers);
        return;
      }
      if (route.request().method() === "POST") {
        const payload = route.request().postDataJSON() as {
          email: string;
          display_name: string;
        };
        const created = {
          id: "synthetic-managed-user",
          email: payload.email.toLowerCase(),
          display_name: payload.display_name,
          created_at: "2026-10-12T12:00:00-03:00",
          mfa_enrolled: false,
        };
        managedUsers = [created, ...managedUsers];
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(created),
        });
        return;
      }
    }
    if (
      url.pathname.endsWith("/mfa/reset") &&
      route.request().method() === "POST" &&
      options.owner
    ) {
      const managedUserId = url.pathname.split("/").at(-3);
      managedUsers = managedUsers.map((managedUser) => managedUser.id === managedUserId
        ? { ...managedUser, mfa_enrolled: false }
        : managedUser);
      await route.fulfill({ status: 204, body: "" });
      return;
    }
    if (
      url.pathname.startsWith("/api/admin/users/") &&
      route.request().method() === "DELETE" &&
      options.owner
    ) {
      const managedUserId = url.pathname.split("/").at(-1);
      managedUsers = managedUsers.filter((managedUser) => managedUser.id !== managedUserId);
      await route.fulfill({ status: 204, body: "" });
      return;
    }
    if (url.pathname === "/api/ai/status") {
      await json(route, {
        configured: true,
        provider: "ollama",
        fast_model: "synthetic",
        smart_model: "synthetic",
        diagnostics_enabled: false,
      });
      return;
    }
    if (url.pathname === "/api/ai/usage") {
      await json(route, {
        calls_today: 0,
        input_tokens_today: 0,
        output_tokens_today: 0,
        cost_usd_today: null,
        calls_month: 0,
        input_tokens_month: 0,
        output_tokens_month: 0,
        cost_usd_month: null,
      });
      return;
    }
    if (url.pathname === "/api/accounts") {
      await json(route, mockAccounts);
      return;
    }
    if (url.pathname === "/api/export") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: {
          "Content-Disposition":
            'attachment; filename="sophia-financas-20261012.json"',
        },
        body: JSON.stringify({
          format: "sophia-finance-export",
          schema_version: 1,
          data: { accounts: [account] },
        }),
      });
      return;
    }
    if (
      url.pathname === "/api/imports/transactions/preview" &&
      route.request().method() === "POST"
    ) {
      state.importPreviewRequests += 1;
      await json(route, {
        preview_token: "synthetic-preview-token-1234567890",
        expires_at: "2026-10-12T12:15:00Z",
        row_count: options.largeLists ? 21 : 2,
        rows: options.largeLists ? Array.from({ length: 21 }, (_, index) => ({
          row_number: index + 2,
          occurred_at: "2026-10-10",
          description: `Compra importada ${index + 1}`,
          type: "EXPENSE",
          amount: "45.90",
          account_name: account.name,
          category_name: "Alimentação",
          matches: [],
          matches_truncated: false,
        })) : [
          {
            row_number: 2,
            occurred_at: "2026-10-10",
            description: "Compra nova",
            type: "EXPENSE",
            amount: "45.90",
            account_name: account.name,
            category_name: "Alimentação",
            matches: [],
            matches_truncated: false,
          },
          {
            row_number: 3,
            occurred_at: "2026-10-11",
            description: "Mercado repetido",
            type: "EXPENSE",
            amount: "25.00",
            account_name: account.name,
            category_name: "Alimentação",
            matches: [
              {
                kind: "exact",
                source: "transaction",
                transaction_id: "synthetic-existing-transaction",
                row_number: null,
                description: "Mercado repetido",
                occurred_at: "2026-10-11",
                amount: "25.00",
              },
            ],
            matches_truncated: false,
          },
        ],
      });
      return;
    }
    if (
      url.pathname === "/api/imports/transactions/confirm" &&
      route.request().method() === "POST"
    ) {
      const body = route.request().postDataJSON() as {
        confirmed: boolean;
        decisions: { row_number: number; action: string }[];
      };
      state.importConfirmRequests.push({
        confirmed: body.confirmed,
        decisions: body.decisions,
      });
      await json(route, { imported_count: 1, skipped_count: 1, imported: [] });
      return;
    }
    if (url.pathname === "/api/categories") {
      await json(route, mockCategories);
      return;
    }
    if (url.pathname === "/api/transactions") {
      state.transactionQueries.push(url.search);
      if (transactionFailuresRemaining > 0) {
        transactionFailuresRemaining -= 1;
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "A consulta de lançamentos falhou." }),
        });
        return;
      }
      const categoryId = url.searchParams.get("category_id");
      const accountId = url.searchParams.get("account_id");
      const type = url.searchParams.get("type");
      const query = url.searchParams.get("q")?.trim().toLocaleLowerCase("pt-BR");
      const startDate = url.searchParams.get("start_date");
      const endDate = url.searchParams.get("end_date");
      const filtered = mockTransactions.filter((transaction) => {
        if (categoryId && transaction.category_id !== categoryId) return false;
        if (accountId && transaction.account_id !== accountId && transaction.source_account_id !== accountId && transaction.destination_account_id !== accountId) return false;
        if (type && transaction.type !== type) return false;
        if (startDate && transaction.occurred_at < startDate) return false;
        if (endDate && transaction.occurred_at > endDate) return false;
        if (query) {
          const searchable = `${transaction.description} ${transaction.notes ?? ""} ${transaction.category_name ?? ""} ${transaction.credit_card_name ?? ""}`.toLocaleLowerCase("pt-BR");
          if (!searchable.includes(query)) return false;
        }
        return true;
      });
      const incomeCents = mockSumCents(filtered, (movementType) => movementType === "INCOME");
      const expenseCents = mockSumCents(filtered, (movementType) => movementType === "EXPENSE");
      const cardPurchaseCents = mockSumCents(filtered, (movementType) => movementType === "CARD_PURCHASE");
      const expensesCents = expenseCents + cardPurchaseCents;
      const summary = {
        transaction_count: filtered.length,
        income_total: mockMoneyFromCents(incomeCents),
        expense_total: mockMoneyFromCents(expenseCents),
        card_purchase_total: mockMoneyFromCents(cardPurchaseCents),
        expenses_total: mockMoneyFromCents(expensesCents),
        transfer_total: mockMoneyFromCents(mockSumCents(filtered, (movementType) => movementType === "TRANSFER")),
        card_payment_total: mockMoneyFromCents(mockSumCents(filtered, (movementType) => movementType === "CARD_PAYMENT")),
        result_total: mockMoneyFromCents(incomeCents - expensesCents),
      };
      const limit = Number(url.searchParams.get("limit") ?? "15");
      const cursorOffset = Number(url.searchParams.get("cursor") ?? "0");
      const items = filtered.slice(cursorOffset, cursorOffset + limit);
      const nextOffset = cursorOffset + items.length;
      const nextCursor = nextOffset < filtered.length ? String(nextOffset) : null;
      await json(route, { items, next_cursor: nextCursor, has_more: nextCursor !== null, summary });
      return;
    }
    if (
      route.request().method() === "GET" &&
      [
        "/api/recurrences",
        "/api/recurrences/occurrences",
        "/api/commitments",
      ].includes(url.pathname)
    ) {
      await json(route, url.pathname === "/api/recurrences"
        ? mockRules
        : url.pathname === "/api/recurrences/occurrences"
          ? mockOccurrences
          : mockCommitments);
      return;
    }
    if (
      url.pathname === "/api/cards" ||
      url.pathname === "/api/cards?include_archived=true"
    ) {
      await json(route, mockCards);
      return;
    }
    if (url.pathname === "/api/dashboard/summary") {
      state.dashboardQueries.push(url.search);
      const year = Number(url.searchParams.get("year") ?? "2026");
      const month = Number(url.searchParams.get("month") ?? "10");
      await json(route, dashboardForMonth(year, month, options.largeLists, options.categoryBreakdown));
      return;
    }
    if (url.pathname === "/api/cards/invoices/upcoming") {
      await json(route, mockUpcomingInvoices);
      return;
    }
    if (url.pathname === "/api/card-purchases" && route.request().method() === "POST") {
      state.cardPurchaseRequests.push(route.request().postDataJSON() as E2EApiState["cardPurchaseRequests"][number]);
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "synthetic-card-purchase" }) });
      return;
    }
    if (
      url.pathname.startsWith("/api/cards/") &&
      url.pathname.endsWith("/invoices")
    ) {
      const cardId = url.pathname.split("/")[3];
      await json(route, mockInvoices(cardId));
      return;
    }
    if (url.pathname === "/api/card-purchase-plans" && route.request().method() === "POST") {
      state.cardPurchasePlanRequests.push(route.request().postDataJSON() as E2EApiState["cardPurchasePlanRequests"][number]);
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "synthetic-purchase-plan", installment_count: 5 }),
      });
      return;
    }
    if (
      url.pathname === "/api/ai/conversations" &&
      route.request().method() === "GET"
    ) {
      await json(
        route,
        options.largeLists
          ? mockConversations
          : conversationCreated
          ? [
              {
                id: CONVERSATION_ID,
                title: "Previsão de novembro",
                created_at: "2026-10-12T12:00:00-03:00",
                updated_at: "2026-10-12T12:00:00-03:00",
              },
            ]
          : [],
      );
      return;
    }
    if (
      url.pathname === "/api/ai/conversations" &&
      route.request().method() === "POST"
    ) {
      conversationCreated = true;
      await json(route, {
        id: CONVERSATION_ID,
        title: "Nova conversa",
        created_at: "2026-10-12T12:00:00-03:00",
        updated_at: "2026-10-12T12:00:00-03:00",
        messages: [],
      });
      return;
    }
    if (url.pathname === `/api/ai/conversations/${CONVERSATION_ID}`) {
      const latestPrompt = state.chatPrompts.at(-1) ?? "";
      const isSpendingQuery = latestPrompt
        .toLocaleLowerCase("pt-BR")
        .includes("quanto gastei");
      await json(route, {
        id: CONVERSATION_ID,
        title: "Previsão de novembro",
        created_at: "2026-10-12T12:00:00-03:00",
        updated_at: "2026-10-12T12:00:00-03:00",
        messages: [
          { id: "synthetic-user-message", role: "USER", content: latestPrompt },
          {
            id: "synthetic-assistant-message",
            role: "ASSISTANT",
            content: isSpendingQuery
              ? "Você gastou R$ 665,43 até agora em outubro."
              : "Aqui está a previsão sintética de novembro.",
            structured_content: isSpendingQuery
              ? [
                  {
                    type: "financial_summary",
                    data: {
                      period_start: "2026-10-01",
                      period_end: "2026-10-31",
                      income: "200.00",
                      expenses: "665.43",
                      result: "-465.43",
                    },
                  },
                ]
              : [
                  {
                    type: "monthly_forecast",
                    data: {
                      period_start: "2026-11-01",
                      period_end: "2026-11-30",
                      expenses: "812.30",
                      income: "0.00",
                      items: [
                        {
                          id: "synthetic-chat-invoice",
                          source: "CARD_INVOICE",
                          type: "EXPENSE",
                          description: "Fatura sintética Nubank",
                          due_date: "2026-11-10",
                          amount: "812.30",
                          card_name: "Nubank",
                        },
                      ],
                    },
                  },
                ],
          },
        ],
      });
      return;
    }
    if (
      url.pathname === `/api/ai/conversations/${CONVERSATION_ID}/messages` &&
      route.request().method() === "POST"
    ) {
      const body = route.request().postDataJSON() as { content?: string };
      if (body.content) state.chatPrompts.push(body.content);
      const isSpendingQuery = (body.content ?? "")
        .toLocaleLowerCase("pt-BR")
        .includes("quanto gastei");
      const answerText = isSpendingQuery
        ? "Você gastou R$ 665,43 até agora em outubro."
        : "Aqui está a previsão sintética de novembro.";
      const structuredItem = isSpendingQuery
        ? {
            type: "financial_summary",
            data: {
              period_start: "2026-10-01",
              period_end: "2026-10-31",
              income: "200.00",
              expenses: "665.43",
              result: "-465.43",
            },
          }
        : {
            type: "monthly_forecast",
            data: {
              period_start: "2026-11-01",
              period_end: "2026-11-30",
              expenses: "812.30",
              income: "0.00",
              items: [
                {
                  id: "synthetic-chat-invoice",
                  source: "CARD_INVOICE",
                  type: "EXPENSE",
                  description: "Fatura sintética Nubank",
                  due_date: "2026-11-10",
                  amount: "812.30",
                  card_name: "Nubank",
                },
              ],
            },
          };
      const answer = `event: text_delta\ndata: ${JSON.stringify({ text: answerText })}\n\nevent: structured\ndata: ${JSON.stringify({ items: [structuredItem] })}\n\nevent: done\ndata: {}\n\n`;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: answer,
      });
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Rota sintética sem fixture" }),
    });
  });

  return state;
}
