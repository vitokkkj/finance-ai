import { createHmac } from "node:crypto";
import { expect, test } from "@playwright/test";

const integrated = process.env.E2E_INTEGRATED === "1";
const totpSecret = process.env.OWNER_TOTP_SECRET;

test.skip(!integrated, "Executado no CI com API e PostgreSQL isolados.");

function totpForCounter(secret: string, counter: number): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const normalized = secret.toUpperCase().replace(/=+$/, "");
  let bits = "";
  for (const character of normalized) {
    const value = alphabet.indexOf(character);
    if (value < 0) throw new Error("OWNER_TOTP_SECRET inválido para o E2E.");
    bits += value.toString(2).padStart(5, "0");
  }
  const key = Buffer.from(
    bits.match(/.{8}/g)?.map((byte) => Number.parseInt(byte, 2)) ?? [],
  );
  const message = Buffer.alloc(8);
  message.writeBigUInt64BE(BigInt(counter));
  const digest = createHmac("sha1", key).update(message).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const binary = digest.readUInt32BE(offset) & 0x7fffffff;
  return String(binary % 1_000_000).padStart(6, "0");
}

async function freshTotp(secret: string, afterCounter?: number) {
  let counter = Math.floor(Date.now() / 30_000);
  while (afterCounter !== undefined && counter <= afterCounter) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    counter = Math.floor(Date.now() / 30_000);
  }
  return { code: totpForCounter(secret, counter), counter };
}

async function setupTotp(secret: string) {
  const remaining = 30_000 - (Date.now() % 30_000);
  if (remaining < 5_000) {
    await new Promise((resolve) => setTimeout(resolve, remaining + 250));
  }
  const counter = Math.floor(Date.now() / 30_000) - 1;
  return { code: totpForCounter(secret, counter), counter };
}

test("primeiro acesso, MFA e fluxos financeiros persistidos pela API", async ({
  page,
}) => {
  test.setTimeout(240_000);
  await page.goto("/");

  const setupName = page.getByLabel("Como podemos chamar você?");
  const email = page.getByLabel("E-mail", { exact: true });
  await expect
    .poll(async () => (await setupName.count()) + (await email.count()))
    .toBeGreaterThan(0);
  let setupCounter: number | undefined;
  let ownerLastCounter: number | undefined;
  if (await setupName.count()) {
    await setupName.fill("Pessoa E2E Sintética");
    await email.fill("gamercreeper74@gmail.com");
    await page
      .getByLabel("Senha", { exact: true })
      .fill("Senha-sintetica-E2E-2026!");
    await expect(
      page.getByLabel("Token temporário de primeiro acesso"),
    ).toHaveCount(0);
    if (totpSecret) {
      const setupCode = await setupTotp(totpSecret);
      setupCounter = setupCode.counter;
      await page
        .getByLabel("Código de seis dígitos do Authy")
        .fill(setupCode.code);
    } else {
      await expect(
        page.getByLabel("Código de seis dígitos do Authy"),
      ).toHaveCount(0);
    }
    await page.getByRole("button", { name: "Criar conta privada" }).click();
    await expect(page.getByRole("status")).toContainText("Conta criada");
  }

  await email.fill("gamercreeper74@gmail.com");
  await page
    .getByLabel("Senha", { exact: true })
    .fill("Senha-sintetica-E2E-2026!");
  await page.getByRole("button", { name: "Continuar" }).click();
  if (totpSecret) {
    await expect(
      page.getByLabel("Código de seis dígitos do Authy"),
    ).toBeVisible();
    const loginTotp = await freshTotp(totpSecret, setupCounter);
    ownerLastCounter = loginTotp.counter;
    await page
      .getByLabel("Código de seis dígitos do Authy")
      .fill(loginTotp.code);
    await page.getByRole("button", { name: "Entrar com MFA" }).click();
  }
  const firstAccountHeading = page.getByRole("heading", {
    name: "Qual conta você quer acompanhar primeiro?",
  });
  const overviewButton = page.getByRole("button", {
    name: "Visão geral",
    exact: true,
  });
  await expect
    .poll(
      async () =>
        (await firstAccountHeading.count()) + (await overviewButton.count()),
    )
    .toBeGreaterThan(0);
  if (await firstAccountHeading.count()) {
    await page.getByLabel("Nome da conta").fill("Conta integrada E2E");
    await page.getByRole("button", { name: "Continuar" }).click();
    await expect(
      page.getByRole("heading", { name: "Sua conta está pronta." }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Ir para o chat" }).click();
  }
  await expect(overviewButton).toBeVisible();

  await page.evaluate(async () => {
    const response = await fetch("/api/categories");
    const categories = await response.json();
    if (!response.ok || !Array.isArray(categories)) {
      throw new Error(`Leitura das categorias respondeu ${response.status}.`);
    }
    if (
      categories.some(
        (item) => item.name === "Categoria de interface integrada E2E",
      )
    ) {
      return;
    }
    const created = await fetch("/api/categories", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-SophIA-Request": "1",
      },
      body: JSON.stringify({
        name: "Categoria de interface integrada E2E",
        type: "EXPENSE",
      }),
    });
    if (!created.ok) {
      throw new Error(`Criação da categoria respondeu ${created.status}.`);
    }
  });

  // Recarrega o workspace para incluir a categoria sintética criada via API.
  await page.reload();
  await expect(overviewButton).toBeVisible();
  await page.getByRole("button", { name: "Lançamentos", exact: true }).click();
  await page.getByRole("button", { name: "Novo lançamento" }).click();
  const transactionForm = page.locator("form.editor-form").filter({
    has: page.getByRole("heading", { name: "Adicionar lançamento" }),
  });
  await expect(transactionForm).toBeVisible();
  await transactionForm.getByLabel("Conta", { exact: true }).selectOption({
    label: "Conta integrada E2E",
  });
  await transactionForm
    .getByLabel("Valor", { exact: true })
    .fill("27,89");
  await transactionForm
    .getByLabel("Descrição", { exact: true })
    .fill("Despesa pela interface integrada E2E");
  await transactionForm
    .getByLabel("Categoria", { exact: true })
    .selectOption({ label: "Categoria de interface integrada E2E" });
  await transactionForm
    .getByRole("button", { name: "Salvar lançamento" })
    .click();
  await expect(page.locator(".workspace-notice.success")).toContainText(
    "Lançamento registrado.",
  );

  const result = await page.evaluate(async () => {
    async function requestJson<T>(
      path: string,
      init?: RequestInit,
    ): Promise<T> {
      const response = await fetch(path, init);
      const body = response.status === 204 ? null : await response.json();
      if (!response.ok) {
        throw new Error(
          `${init?.method ?? "GET"} ${path} respondeu ${response.status}: ${JSON.stringify(body)}`,
        );
      }
      return body as T;
    }

    const postJson = <T>(path: string, body: unknown, key?: string) =>
      requestJson<T>(path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-SophIA-Request": "1",
          ...(key ? { "Idempotency-Key": key } : {}),
        },
        body: JSON.stringify(body),
      });

    const accountsResponse = await fetch("/api/accounts");
    const accounts = await accountsResponse.json();
    if (!accountsResponse.ok || !Array.isArray(accounts)) {
      throw new Error(
        `Leitura das contas respondeu ${accountsResponse.status}.`,
      );
    }
    const account = accounts.find(
      (item) => item.name === "Conta integrada E2E",
    );
    if (!account) {
      throw new Error(
        "A conta sintética criada no primeiro uso não foi encontrada.",
      );
    }
    let destination = accounts.find(
      (item) => item.name === "Conta secundária integrada E2E",
    );
    if (!destination) {
      destination = await postJson("/api/accounts", {
        name: "Conta secundária integrada E2E",
        type: "SAVINGS",
      });
    }

    const categoriesResponse = await fetch("/api/categories");
    const categories = await categoriesResponse.json();
    if (!categoriesResponse.ok || !Array.isArray(categories)) {
      throw new Error(
        `Leitura das categorias respondeu ${categoriesResponse.status}.`,
      );
    }
    let category = categories.find(
      (item) => item.name === "Categoria integrada E2E",
    );
    if (!category) {
      category = await postJson("/api/categories", {
        name: "Categoria integrada E2E",
        type: "EXPENSE",
      });
    }

    const payload = {
      account_id: account.id,
      category_id: category.id,
      type: "EXPENSE",
      description: "Compra sintética integrada E2E",
      amount: "12.34",
      occurred_at: new Date().toLocaleDateString("sv-SE", {
        timeZone: "America/Sao_Paulo",
      }),
    };
    const first = await postJson<Record<string, unknown>>(
      "/api/transactions",
      payload,
      "integrated-e2e-transaction-001",
    );
    const retry = await postJson<Record<string, unknown>>(
      "/api/transactions",
      payload,
      "integrated-e2e-transaction-001",
    );

    const listResponse = await fetch("/api/transactions");
    const transactionPage = await listResponse.json();
    const transactions = transactionPage.items;
    if (!listResponse.ok || !Array.isArray(transactions)) {
      throw new Error(
        `Leitura dos lançamentos respondeu ${listResponse.status}.`,
      );
    }
    const uiTransaction = transactions.find(
      (transaction) =>
        transaction.description === "Despesa pela interface integrada E2E",
    );
    if (!uiTransaction) {
      throw new Error("O lançamento feito pela interface não persistiu na API.");
    }

    const transferPayload = {
      source_account_id: account.id,
      destination_account_id: destination.id,
      amount: "1.00",
      occurred_at: payload.occurred_at,
    };
    const transfer = await postJson<Record<string, unknown>>(
      "/api/transfers",
      transferPayload,
      "integrated-e2e-transfer-001",
    );
    const transferRetry = await postJson<Record<string, unknown>>(
      "/api/transfers",
      transferPayload,
      "integrated-e2e-transfer-001",
    );

    const cards =
      await requestJson<Array<Record<string, unknown>>>("/api/cards");
    let card = cards.find((item) => item.name === "Cartão integrado E2E");
    if (!card) {
      card = await postJson<Record<string, unknown>>("/api/cards", {
        name: "Cartão integrado E2E",
        credit_limit: "1000.00",
        closing_day: 20,
        due_day: 5,
        payment_account_id: account.id,
      });
    }
    if (!card) throw new Error("O cartão sintético não foi criado.");
    const cardPurchasePayload = {
      credit_card_id: card.id,
      category_id: category.id,
      description: "Compra sintética no cartão E2E",
      amount: "12.34",
      occurred_at: payload.occurred_at,
    };
    const cardPurchase = await postJson<Record<string, unknown>>(
      "/api/card-purchases",
      cardPurchasePayload,
      "integrated-e2e-card-purchase-001",
    );
    const cardPurchaseRetry = await postJson<Record<string, unknown>>(
      "/api/card-purchases",
      cardPurchasePayload,
      "integrated-e2e-card-purchase-001",
    );
    const invoices = await requestJson<Array<Record<string, unknown>>>(
      `/api/cards/${card.id}/invoices`,
    );
    const invoice = invoices.find((item) => item.total === "12.34");
    if (!invoice) throw new Error("A fatura sintética não foi criada.");
    const paymentPayload = {
      account_id: account.id,
      amount: "12.34",
      occurred_at: payload.occurred_at,
    };
    const paymentPath = `/api/invoices/${invoice.id}/payments`;
    const payment = await postJson<Record<string, unknown>>(
      paymentPath,
      paymentPayload,
      "integrated-e2e-invoice-payment-001",
    );
    const paymentRetry = await postJson<Record<string, unknown>>(
      paymentPath,
      paymentPayload,
      "integrated-e2e-invoice-payment-001",
    );
    const payments =
      await requestJson<Array<Record<string, unknown>>>(paymentPath);
    const managedUser = await postJson<Record<string, unknown>>(
      "/api/admin/users",
      {
        email: "acesso-e2e@example.invalid",
        display_name: "Acesso integrado E2E",
        password: "Senha-sintetica-E2E-2026!",
      },
    );
    return {
      first,
      retry,
      transfer,
      transferRetry,
      cardPurchase,
      cardPurchaseRetry,
      payment,
      paymentRetry,
      payments,
      uiTransaction,
      managedUserId: managedUser.id,
      matching: transactions.filter(
        (transaction) =>
          transaction.description === "Compra sintética integrada E2E",
      ),
    };
  });

  expect(result.first).toMatchObject({
    description: "Compra sintética integrada E2E",
    amount: "12.34",
  });
  expect(result.uiTransaction).toMatchObject({
    description: "Despesa pela interface integrada E2E",
    amount: "27.89",
    type: "EXPENSE",
    category_name: "Categoria de interface integrada E2E",
  });
  expect(result.retry.id).toBe(result.first.id);
  expect(result.matching).toHaveLength(1);
  expect(result.transferRetry.id).toBe(result.transfer.id);
  expect(result.cardPurchaseRetry.id).toBe(result.cardPurchase.id);
  expect(result.paymentRetry.id).toBe(result.payment.id);
  expect(result.payments).toHaveLength(1);
  expect(result.managedUserId).toEqual(expect.any(String));

  if (totpSecret) {
    const managedEmail = "acesso-e2e@example.invalid";
    const managedPassword = "Senha-sintetica-E2E-2026!";
    await page.getByRole("button", { name: "Sair" }).click();
    await expect(page.getByLabel("E-mail", { exact: true })).toBeVisible();

    await page.getByLabel("E-mail", { exact: true }).fill(managedEmail);
    await page.getByLabel("Senha", { exact: true }).fill(managedPassword);
    await page.getByRole("button", { name: "Continuar" }).click();
    await page.getByRole("button", { name: "Configurar autenticador" }).click();
    await page.getByRole("button", { name: "Gerar QR code" }).click();
    const manualKey = page.locator(".mfa-enrollment-qr-panel code");
    await page.getByText("Não consegue escanear?").click();
    await expect(manualKey).toBeVisible();
    const managedSecret = (await manualKey.innerText()).trim();
    const pairingCode = await freshTotp(managedSecret);
    await page
      .getByLabel("Código de seis dígitos do Authy")
      .fill(pairingCode.code);
    await page.getByRole("button", { name: "Confirmar e entrar" }).click();
    await expect(
      page.getByRole("heading", {
        name: "Qual conta você quer acompanhar primeiro?",
      }),
    ).toBeVisible();

    // The managed user has no financial rows, so logging out via the authenticated API
    // keeps the synthetic account eligible for deletion after the owner reset check.
    const firstManagedLogout = await page.evaluate(async () =>
      fetch("/api/auth/logout", {
        method: "POST",
        headers: { "X-SophIA-Request": "1" },
      }).then((response) => response.status),
    );
    expect(firstManagedLogout).toBe(200);
    await page.reload();
    await expect(page.getByLabel("E-mail", { exact: true })).toBeVisible();

    await page.getByLabel("E-mail", { exact: true }).fill(managedEmail);
    await page.getByLabel("Senha", { exact: true }).fill(managedPassword);
    await page.getByRole("button", { name: "Continuar" }).click();
    await expect(
      page.getByLabel("Código de seis dígitos do Authy"),
    ).toBeVisible();
    const managedLoginCode = await freshTotp(
      managedSecret,
      pairingCode.counter,
    );
    await page
      .getByLabel("Código de seis dígitos do Authy")
      .fill(managedLoginCode.code);
    await page.getByRole("button", { name: "Entrar com MFA" }).click();
    await expect(
      page.getByRole("heading", {
        name: "Qual conta você quer acompanhar primeiro?",
      }),
    ).toBeVisible();
    const secondManagedLogout = await page.evaluate(async () =>
      fetch("/api/auth/logout", {
        method: "POST",
        headers: { "X-SophIA-Request": "1" },
      }).then((response) => response.status),
    );
    expect(secondManagedLogout).toBe(200);
    await page.reload();
    await expect(page.getByLabel("E-mail", { exact: true })).toBeVisible();

    await page.getByLabel("E-mail", { exact: true }).fill("gamercreeper74@gmail.com");
    await page
      .getByLabel("Senha", { exact: true })
      .fill("Senha-sintetica-E2E-2026!");
    await page.getByRole("button", { name: "Continuar" }).click();
    await expect(
      page.getByLabel("Código de seis dígitos do Authy"),
    ).toBeVisible();
    const ownerResetCode = await freshTotp(totpSecret, ownerLastCounter);
    ownerLastCounter = ownerResetCode.counter;
    await page
      .getByLabel("Código de seis dígitos do Authy")
      .fill(ownerResetCode.code);
    await page.getByRole("button", { name: "Entrar com MFA" }).click();
    await expect(
      page.getByRole("button", { name: "Visão geral", exact: true }),
    ).toBeVisible();

    await page.getByRole("button", { name: "Preferências", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Preferências da SophIA" }),
    ).toBeVisible();
    const managedUserRow = page
      .locator(".settings-managed-user-row")
      .filter({ hasText: managedEmail });
    await expect(managedUserRow).toContainText("Autenticador configurado");
    await managedUserRow.getByRole("button", { name: "Redefinir MFA" }).click();
    await managedUserRow.getByLabel("Sua senha").fill("Senha-sintetica-E2E-2026!");
    const ownerReauthenticationCode = await freshTotp(
      totpSecret,
      ownerLastCounter,
    );
    ownerLastCounter = ownerReauthenticationCode.counter;
    await managedUserRow
      .getByLabel("Seu código MFA")
      .fill(ownerReauthenticationCode.code);
    await managedUserRow
      .getByRole("button", { name: "Confirmar redefinição" })
      .click();
    await expect(managedUserRow).toContainText("Autenticador pendente");

    const cleanup = await page.evaluate(async (userId) => {
      const response = await fetch(`/api/admin/users/${userId}`, {
        method: "DELETE",
        headers: { "X-SophIA-Request": "1" },
      });
      const usersResponse = await fetch("/api/admin/users");
      const users = await usersResponse.json();
      return {
        deleteStatus: response.status,
        remainingManagedUsers: Array.isArray(users)
          ? users.filter((user) => user.email !== "gamercreeper74@gmail.com")
              .length
          : -1,
      };
    }, result.managedUserId as string);
    expect(cleanup.deleteStatus).toBe(204);
    expect(cleanup.remainingManagedUsers).toBe(0);
  } else {
    const cleanup = await page.evaluate(async (userId) =>
      fetch(`/api/admin/users/${userId}`, {
        method: "DELETE",
        headers: { "X-SophIA-Request": "1" },
      }).then((response) => response.status),
    result.managedUserId as string);
    expect(cleanup).toBe(204);
  }
});
