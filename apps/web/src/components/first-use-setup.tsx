"use client";

import { useState, type FormEvent } from "react";

import { apiRequest } from "@/lib/api";
import { toDecimalString } from "@/lib/money";
import { CurrencyInput } from "@/components/currency-input";

type AccountType = "CHECKING" | "SAVINGS" | "CASH" | "OTHER";

function dateInSaoPaulo(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const part = (type: string) => parts.find((entry) => entry.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function FirstUseSetup({
  displayName,
  onOpenCards,
  onComplete,
}: {
  displayName: string;
  onOpenCards: () => void;
  onComplete: () => void;
}) {
  const [name, setName] = useState("");
  const [type, setType] = useState<AccountType>("CHECKING");
  const [openingBalance, setOpeningBalance] = useState("");
  const [openingBalanceDate, setOpeningBalanceDate] = useState(dateInSaoPaulo);
  const [accountCreated, setAccountCreated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function createAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const hasOpeningBalance = openingBalance.trim().length > 0;
      await apiRequest("/api/accounts", {
        method: "POST",
        body: JSON.stringify({
          name,
          type,
          opening_balance: hasOpeningBalance ? toDecimalString(openingBalance) : null,
          opening_balance_date: hasOpeningBalance ? openingBalanceDate : null,
        }),
      });
      setAccountCreated(true);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Não foi possível cadastrar sua conta.");
    } finally {
      setBusy(false);
    }
  }

  const firstName = displayName.trim().split(/\s+/)[0] || displayName;

  return (
    <main className="auth-page first-use-page">
      <section className="auth-brand-lockup" aria-label="SophIA — sua assistente financeira">
        <span className="assistant-brand-mark" aria-hidden="true">S</span>
        <span className="auth-brand-copy"><strong>SophIA</strong><small>sua assistente financeira</small></span>
      </section>

      {!accountCreated ? (
        <section className="auth-card first-use-card">
          <div className="auth-heading">
            <p className="eyebrow">Vamos começar, {firstName}</p>
            <h2>Qual conta você quer acompanhar primeiro?</h2>
            <p>Comece pela conta onde você centraliza o saldo. Você poderá adicionar outras depois.</p>
          </div>
          <form className="auth-form" onSubmit={(event) => void createAccount(event)}>
            <label className="field-label">
              Nome da conta
              <input
                autoComplete="off"
                maxLength={100}
                onChange={(event) => setName(event.target.value)}
                placeholder="Ex.: Sicredi"
                required
                value={name}
              />
            </label>
            <label className="field-label">
              Tipo de conta
              <select onChange={(event) => setType(event.target.value as AccountType)} value={type}>
                <option value="CHECKING">Conta corrente</option>
                <option value="SAVINGS">Poupança</option>
                <option value="CASH">Dinheiro</option>
                <option value="OTHER">Outra</option>
              </select>
            </label>
            <div className="field-label">
              <label htmlFor="first-use-opening-balance">Saldo inicial (opcional)</label>
              <CurrencyInput
                id="first-use-opening-balance"
                onChange={setOpeningBalance}
                placeholder="0,00"
                value={openingBalance}
              />
            </div>
            <label className="field-label">
              Data desse saldo
              <input
                disabled={!openingBalance.trim()}
                onChange={(event) => setOpeningBalanceDate(event.target.value)}
                required={Boolean(openingBalance.trim())}
                type="date"
                value={openingBalanceDate}
              />
            </label>
            <p className="first-use-note">
              Sem valor e data, sua conta fica cadastrada, mas a SophIA não calcula nem exibe um saldo
              como se fosse conhecido. Você pode completar isso depois.
            </p>
            {error && <p className="form-message" role="alert">{error}</p>}
            <button className="primary-button" disabled={busy} type="submit">
              {busy ? "Salvando…" : "Continuar"}<span aria-hidden="true">↗</span>
            </button>
          </form>
        </section>
      ) : (
        <section className="auth-card first-use-card">
          <div className="auth-heading">
            <p className="eyebrow">Primeiro passo concluído</p>
            <h2>Sua conta está pronta.</h2>
            <p>Cartões são opcionais. Você pode cadastrar um agora ou seguir para conversar com a SophIA.</p>
          </div>
          <div className="first-use-actions">
            <button className="primary-button" onClick={onComplete} type="button">Ir para o chat<span aria-hidden="true">↗</span></button>
            <button className="secondary-button" onClick={onOpenCards} type="button">Cadastrar um cartão</button>
          </div>
        </section>
      )}
      <p className="auth-page-footer">SophIA <span>·</span> Seu espaço financeiro privado</p>
    </main>
  );
}
