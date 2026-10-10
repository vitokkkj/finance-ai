"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { apiRequest } from "@/lib/api";
import { formatCurrency, toDecimalString } from "@/lib/money";
import { CurrencyInput } from "@/components/currency-input";
import { CalendarDateInput } from "@/components/calendar-date-input";

type Account = { id: string; name: string; is_active: boolean };
type Category = { id: string; name: string; type: "INCOME" | "EXPENSE"; is_archived: boolean };
type CreditCard = {
  id: string;
  name: string;
  institution: string | null;
  credit_limit: string;
  closing_day: number;
  due_day: number;
  is_active: boolean;
  used_limit: string;
  available_limit: string;
  next_due_date: string | null;
};
type InvoiceItem = {
  id: string;
  description: string;
  amount: string;
  occurred_at: string;
  notes: string | null;
};
type CardInvoice = {
  id: string;
  credit_card_id: string;
  credit_card_name: string;
  period_start: string;
  period_end: string;
  closing_date: string;
  due_date: string;
  opening_balance: string;
  total: string;
  paid_amount: string;
  outstanding: string;
  status: "OPEN" | "CLOSED" | "PARTIALLY_PAID" | "PAID" | "OVERDUE";
  purchases: InvoiceItem[];
  payments: InvoiceItem[];
};
type CardForm = {
  name: string;
  institution: string;
  credit_limit: string;
  closing_day: string;
  due_day: string;
};
type Notice = { kind: "success" | "error"; message: string } | null;

function localDate(): string {
  const pieces = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const part = (key: string) => pieces.find((item) => item.type === key)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function localMonth(): string {
  return localDate().slice(0, 7);
}

function displayDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function emptyCard(): CardForm {
  return { name: "", institution: "", credit_limit: "", closing_day: "13", due_day: "20" };
}

function statusLabel(status: CardInvoice["status"]): string {
  const labels: Record<CardInvoice["status"], string> = {
    OPEN: "Em aberto",
    CLOSED: "Fechada",
    PARTIALLY_PAID: "Parcialmente paga",
    PAID: "Quitada",
    OVERDUE: "Atrasada",
  };
  return labels[status];
}

export function CreditCardWorkspace({
  accounts,
  categories,
  onFinanceChanged,
}: {
  accounts: Account[];
  categories: Category[];
  onFinanceChanged: () => void;
}) {
  const [cards, setCards] = useState<CreditCard[]>([]);
  const [invoices, setInvoices] = useState<CardInvoice[]>([]);
  const [selectedCardId, setSelectedCardId] = useState("");
  const [selectedInvoiceId, setSelectedInvoiceId] = useState("");
  const [cardFormOpen, setCardFormOpen] = useState(false);
  const [cardEditingId, setCardEditingId] = useState<string | null>(null);
  const [cardForm, setCardForm] = useState<CardForm>(emptyCard);
  const [purchaseFormOpen, setPurchaseFormOpen] = useState(false);
  const [purchaseForm, setPurchaseForm] = useState({
    credit_card_id: "",
    category_id: "",
    description: "",
    amount: "",
    occurred_at: localDate(),
    notes: "",
  });
  const [paymentForm, setPaymentForm] = useState({ account_id: "", amount: "", occurred_at: localDate() });
  const [openingInvoiceFormOpen, setOpeningInvoiceFormOpen] = useState(false);
  const [openingInvoiceForm, setOpeningInvoiceForm] = useState({ closing_month: localMonth(), amount: "" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);

  const activeCards = useMemo(() => cards.filter((card) => card.is_active), [cards]);
  const activeAccounts = useMemo(() => accounts.filter((account) => account.is_active), [accounts]);
  const expenseCategories = useMemo(
    () => categories.filter((category) => !category.is_archived && category.type === "EXPENSE"),
    [categories],
  );
  const selectedInvoice = invoices.find((invoice) => invoice.id === selectedInvoiceId) ?? null;

  const loadCards = useCallback(async () => {
    try {
      const rows = await apiRequest<CreditCard[]>("/api/cards?include_archived=true");
      setCards(rows);
      setSelectedCardId((current) => current || rows.find((card) => card.is_active)?.id || "");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível carregar os cartões." });
    }
  }, []);

  const loadInvoices = useCallback(async () => {
    if (!selectedCardId) {
      setInvoices([]);
      setSelectedInvoiceId("");
      return;
    }
    try {
      const rows = await apiRequest<CardInvoice[]>(`/api/cards/${selectedCardId}/invoices`);
      setInvoices(rows);
      setSelectedInvoiceId((current) => (rows.some((invoice) => invoice.id === current) ? current : ""));
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível carregar as faturas." });
    }
  }, [selectedCardId]);

  useEffect(() => {
    void loadCards();
  }, [loadCards]);

  useEffect(() => {
    void loadInvoices();
  }, [loadInvoices]);

  async function refresh(message: string) {
    setNotice({ kind: "success", message });
    await Promise.all([loadCards(), loadInvoices()]);
    onFinanceChanged();
  }

  function editCard(card: CreditCard) {
    setCardEditingId(card.id);
    setCardForm({
      name: card.name,
      institution: card.institution ?? "",
      credit_limit: card.credit_limit,
      closing_day: String(card.closing_day),
      due_day: String(card.due_day),
    });
    setCardFormOpen(true);
  }

  async function saveCard(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNotice(null);
    try {
      const payload = {
        name: cardForm.name,
        institution: cardForm.institution || null,
        credit_limit: toDecimalString(cardForm.credit_limit),
        closing_day: Number(cardForm.closing_day),
        due_day: Number(cardForm.due_day),
      };
      if (cardEditingId) {
        await apiRequest<CreditCard>(`/api/cards/${cardEditingId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        await apiRequest<CreditCard>("/api/cards", { method: "POST", body: JSON.stringify(payload) });
      }
      const wasEditing = cardEditingId !== null;
      setCardForm(emptyCard());
      setCardFormOpen(false);
      setCardEditingId(null);
      await refresh(wasEditing ? "Cartão atualizado." : "Cartão criado.");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível salvar o cartão." });
    } finally {
      setBusy(false);
    }
  }

  async function archiveCard(card: CreditCard) {
    if (!window.confirm(`Arquivar o cartão “${card.name}”?`)) return;
    setBusy(true);
    try {
      await apiRequest<CreditCard>(`/api/cards/${card.id}/archive`, { method: "POST" });
      await refresh("Cartão arquivado. As faturas e compras continuam no histórico.");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível arquivar." });
    } finally {
      setBusy(false);
    }
  }

  async function createPurchase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      await apiRequest("/api/card-purchases", {
        method: "POST",
        body: JSON.stringify({
          ...purchaseForm,
          amount: toDecimalString(purchaseForm.amount),
          notes: purchaseForm.notes || null,
        }),
      });
      setPurchaseForm({ ...purchaseForm, description: "", amount: "", notes: "" });
      setPurchaseFormOpen(false);
      await refresh("Compra registrada na fatura. O saldo das contas não mudou.");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível registrar a compra." });
    } finally {
      setBusy(false);
    }
  }

  async function payInvoice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedInvoice) return;
    setBusy(true);
    try {
      await apiRequest(`/api/invoices/${selectedInvoice.id}/payments`, {
        method: "POST",
        body: JSON.stringify({ ...paymentForm, amount: toDecimalString(paymentForm.amount) }),
      });
      setPaymentForm({ ...paymentForm, amount: "" });
      await refresh("Pagamento registrado. O pagamento não cria uma nova despesa.");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível pagar a fatura." });
    } finally {
      setBusy(false);
    }
  }

  async function saveOpeningInvoice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedCard = activeCards.find((card) => card.id === selectedCardId) ?? activeCards[0];
    if (!selectedCard) return;
    setBusy(true);
    setNotice(null);
    try {
      const invoice = await apiRequest<CardInvoice>(
        `/api/cards/${selectedCard.id}/invoices/opening-balance`,
        {
          method: "PUT",
          body: JSON.stringify({
            closing_month: openingInvoiceForm.closing_month,
            amount: toDecimalString(openingInvoiceForm.amount),
          }),
        },
      );
      setSelectedCardId(selectedCard.id);
      setSelectedInvoiceId(invoice.id);
      setOpeningInvoiceForm({ closing_month: openingInvoiceForm.closing_month, amount: "" });
      setOpeningInvoiceFormOpen(false);
      await refresh("Saldo da fatura importado. Ele não foi lançado como despesa.");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível registrar a fatura existente." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card-workspace">
      {notice && <div className={`workspace-notice ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.message}</div>}

      <section className="surface-card data-card">
        <div className="surface-heading">
          <div><p className="eyebrow">Crédito</p><h2>Cartões</h2></div>
          <button className="primary-button compact-button" onClick={() => { setCardEditingId(null); setCardForm(emptyCard()); setCardFormOpen(true); }} type="button">＋ Novo cartão</button>
        </div>
        {cardFormOpen && (
          <form className="editor-form" onSubmit={saveCard}>
            <div className="editor-heading"><h3>{cardEditingId ? "Editar cartão" : "Adicionar cartão"}</h3><button className="text-button" onClick={() => setCardFormOpen(false)} type="button">Fechar</button></div>
            <div className="form-grid transaction-form-grid">
              <label className="field-label">Nome<input maxLength={100} onChange={(event) => setCardForm({ ...cardForm, name: event.target.value })} required value={cardForm.name} /></label>
              <label className="field-label">Instituição<input maxLength={100} onChange={(event) => setCardForm({ ...cardForm, institution: event.target.value })} value={cardForm.institution} /></label>
              <div className="field-label"><label htmlFor="credit-card-limit">Limite</label><CurrencyInput id="credit-card-limit" onChange={(value) => setCardForm({ ...cardForm, credit_limit: value })} placeholder="0,00" required value={cardForm.credit_limit} /></div>
              <label className="field-label">Dia de fechamento<input max={31} min={1} onChange={(event) => setCardForm({ ...cardForm, closing_day: event.target.value })} required type="number" value={cardForm.closing_day} /></label>
              <label className="field-label">Dia de vencimento<input max={31} min={1} onChange={(event) => setCardForm({ ...cardForm, due_day: event.target.value })} required type="number" value={cardForm.due_day} /></label>
            </div>
            <div className="form-actions"><button className="primary-button compact-button" disabled={busy} type="submit">{busy ? "Salvando…" : "Salvar cartão"}</button><span className="form-note">Quando o dia não existe no mês, usamos o último dia daquele mês.</span></div>
          </form>
        )}
        {cards.length === 0 ? <EmptyState actionLabel="Cadastrar primeiro cartão" message="Cadastre um cartão para acompanhar compras e faturas." onAction={() => { setCardEditingId(null); setCardForm(emptyCard()); setCardFormOpen(true); }} /> : (
          <div className="table-wrap"><table className="data-table"><thead><tr><th>Cartão</th><th>Limite</th><th>Utilizado</th><th>Disponível</th><th>Próximo vencimento</th><th>Situação</th><th aria-label="Ações" /></tr></thead><tbody>
            {cards.map((card) => <tr key={card.id}><td><strong className="cell-primary">{card.name}</strong><small className="cell-secondary">{card.institution ?? "Cartão de crédito"} · fecha {card.closing_day} · vence {card.due_day}</small></td><td className="table-money">{formatCurrency(card.credit_limit)}</td><td className="table-money">{formatCurrency(card.used_limit)}</td><td className="table-money">{formatCurrency(card.available_limit)}</td><td>{card.next_due_date ? displayDate(card.next_due_date) : "—"}</td><td><span className={card.is_active ? "state-pill active" : "state-pill archived"}>{card.is_active ? "Ativo" : "Arquivado"}</span></td><td className="row-actions">{card.is_active && <><button className="table-action" onClick={() => editCard(card)} type="button">Editar</button><button className="table-action danger-action" disabled={busy} onClick={() => void archiveCard(card)} type="button">Arquivar</button></>}</td></tr>)}
          </tbody></table></div>
        )}
      </section>

      <section className="surface-card data-card">
        <div className="surface-heading">
          <div><p className="eyebrow">Consumo</p><h2>Compras no cartão</h2></div>
          <button className="primary-button compact-button" disabled={activeCards.length === 0} onClick={() => { setPurchaseForm({ ...purchaseForm, credit_card_id: purchaseForm.credit_card_id || (activeCards.length === 1 ? activeCards[0]?.id ?? "" : ""), category_id: purchaseForm.category_id || (expenseCategories.length === 1 ? expenseCategories[0]?.id ?? "" : "") }); setPurchaseFormOpen(true); }} type="button">＋ Nova compra</button>
        </div>
        {purchaseFormOpen && (
          <form className="editor-form" onSubmit={createPurchase}>
            <div className="editor-heading"><h3>Registrar compra</h3><button className="text-button" onClick={() => setPurchaseFormOpen(false)} type="button">Fechar</button></div>
            <div className="form-grid transaction-form-grid">
              <label className="field-label">Cartão<select onChange={(event) => setPurchaseForm({ ...purchaseForm, credit_card_id: event.target.value })} required value={purchaseForm.credit_card_id}><option value="">Selecione</option>{activeCards.map((card) => <option key={card.id} value={card.id}>{card.name}</option>)}</select></label>
              <div className="field-label"><label htmlFor="card-purchase-date">Data</label><CalendarDateInput id="card-purchase-date" onChange={(value) => setPurchaseForm({ ...purchaseForm, occurred_at: value })} required value={purchaseForm.occurred_at} /></div>
              <label className="field-label">Categoria<select onChange={(event) => setPurchaseForm({ ...purchaseForm, category_id: event.target.value })} required value={purchaseForm.category_id}><option value="">Selecione</option>{expenseCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
              <label className="field-label">Descrição<input maxLength={200} onChange={(event) => setPurchaseForm({ ...purchaseForm, description: event.target.value })} required value={purchaseForm.description} /></label>
              <div className="field-label"><label htmlFor="card-purchase-amount">Valor</label><CurrencyInput id="card-purchase-amount" onChange={(value) => setPurchaseForm({ ...purchaseForm, amount: value })} placeholder="0,00" required value={purchaseForm.amount} /></div>
              <label className="field-label full-width-field">Observações<textarea maxLength={2000} onChange={(event) => setPurchaseForm({ ...purchaseForm, notes: event.target.value })} rows={2} value={purchaseForm.notes} /></label>
            </div>
            {(activeCards.length === 0 || expenseCategories.length === 0) && <p className="form-helper">Cadastre um cartão ativo e uma categoria de despesa antes de registrar compras.</p>}
            <div className="form-actions"><button className="primary-button compact-button" disabled={busy || activeCards.length === 0 || expenseCategories.length === 0} type="submit">{busy ? "Salvando…" : "Registrar compra"}</button><span className="form-note">A compra conta como despesa e aumenta a fatura.</span></div>
          </form>
        )}
      </section>

      <section className="surface-card data-card">
        <div className="surface-heading"><div><p className="eyebrow">Ciclos mensais</p><h2>Faturas</h2></div><div className="invoice-heading-actions"><label className="month-picker">Cartão<select onChange={(event) => { setSelectedCardId(event.target.value); setSelectedInvoiceId(""); }} value={selectedCardId}><option value="">Selecione</option>{cards.map((card) => <option key={card.id} value={card.id}>{card.name}{card.is_active ? "" : " (arquivado)"}</option>)}</select></label><button className="secondary-button compact-button" disabled={activeCards.length === 0} onClick={() => { const card = activeCards.find((item) => item.id === selectedCardId) ?? activeCards[0]; if (card) setSelectedCardId(card.id); setOpeningInvoiceFormOpen(true); }} type="button">＋ Registrar fatura existente</button></div></div>
        {openingInvoiceFormOpen && (
          <form className="editor-form opening-invoice-form" onSubmit={(event) => void saveOpeningInvoice(event)}>
            <div className="editor-heading"><div><h3>Saldo de uma fatura existente</h3><p className="form-note">Registre o total que já deve ao cartão. Isso aumenta o valor em aberto, sem criar uma despesa histórica.</p></div><button aria-label="Fechar formulário" className="text-button" onClick={() => setOpeningInvoiceFormOpen(false)} type="button">Fechar</button></div>
            <div className="form-grid transaction-form-grid">
              <label className="field-label">Cartão<select onChange={(event) => setSelectedCardId(event.target.value)} required value={selectedCardId}><option value="">Selecione</option>{activeCards.map((card) => <option key={card.id} value={card.id}>{card.name}</option>)}</select></label>
              <label className="field-label">Mês de fechamento<input onChange={(event) => setOpeningInvoiceForm({ ...openingInvoiceForm, closing_month: event.target.value })} required type="month" value={openingInvoiceForm.closing_month} /><small>O vencimento é calculado pelos dias de fechamento e vencimento deste cartão.</small></label>
              <div className="field-label"><label htmlFor="invoice-opening-amount">Saldo da fatura</label><CurrencyInput id="invoice-opening-amount" onChange={(value) => setOpeningInvoiceForm({ ...openingInvoiceForm, amount: value })} placeholder="0,00" required value={openingInvoiceForm.amount} /></div>
            </div>
            <div className="form-actions"><button className="primary-button compact-button" disabled={busy || !selectedCardId} type="submit">{busy ? "Salvando…" : "Registrar saldo"}</button><span className="form-note">O pagamento poderá ser registrado depois e reduzirá o saldo da conta selecionada.</span></div>
          </form>
        )}
        {invoices.length === 0 ? <EmptyState actionLabel={cards.length === 0 ? "Cadastrar cartão" : "Registrar fatura existente"} message={cards.length === 0 ? "Cadastre um cartão para acompanhar suas faturas." : "Informe o saldo de uma fatura que já existe ou registre a primeira compra no cartão."} onAction={() => {
          if (cards.length === 0) {
            setCardEditingId(null);
            setCardForm(emptyCard());
            setCardFormOpen(true);
          } else {
            const card = activeCards.find((item) => item.id === selectedCardId) ?? activeCards[0];
            if (card) setSelectedCardId(card.id);
            setOpeningInvoiceFormOpen(true);
          }
        }} /> : (
          <div className="table-wrap"><table className="data-table"><thead><tr><th>Ciclo</th><th>Fechamento</th><th>Vencimento</th><th>Total</th><th>Pago</th><th>Em aberto</th><th>Status</th><th /></tr></thead><tbody>
            {invoices.map((invoice) => <tr key={invoice.id}><td>{displayDate(invoice.period_start)} – {displayDate(invoice.period_end)}</td><td>{displayDate(invoice.closing_date)}</td><td>{displayDate(invoice.due_date)}</td><td className="table-money">{formatCurrency(invoice.total)}</td><td>{formatCurrency(invoice.paid_amount)}</td><td>{formatCurrency(invoice.outstanding)}</td><td><span className={`state-pill ${invoice.status === "PAID" ? "active" : "archived"}`}>{statusLabel(invoice.status)}</span></td><td className="row-actions"><button className="table-action" onClick={() => { setSelectedInvoiceId(invoice.id); setPaymentForm({ account_id: activeAccounts.length === 1 ? activeAccounts[0]?.id ?? "" : "", amount: invoice.outstanding, occurred_at: localDate() }); }} type="button">Detalhes / pagar</button></td></tr>)}
          </tbody></table></div>
        )}
        {selectedInvoice && (
          <div className="invoice-details">
            <div className="surface-heading invoice-details-heading">
              <div className="invoice-details-title">
                <p className="eyebrow">{selectedInvoice.credit_card_name}</p>
                <h3>Detalhes da fatura</h3>
                <p className="invoice-details-meta">Ciclo {displayDate(selectedInvoice.period_start)} a {displayDate(selectedInvoice.period_end)} · vence em {displayDate(selectedInvoice.due_date)}</p>
              </div>
              <div className="invoice-details-actions">
                <span className={`state-pill ${selectedInvoice.status === "PAID" ? "active" : "archived"}`}>{statusLabel(selectedInvoice.status)}</span>
                <button className="text-button" onClick={() => setSelectedInvoiceId("")} type="button">Fechar</button>
              </div>
            </div>
            <section aria-label="Resumo da fatura" className="invoice-summary-strip">
              <div><span>Total da fatura</span><strong>{formatCurrency(selectedInvoice.total)}</strong></div>
              <div><span>Já pago</span><strong>{formatCurrency(selectedInvoice.paid_amount)}</strong></div>
              <div><span>Em aberto</span><strong>{formatCurrency(selectedInvoice.outstanding)}</strong></div>
            </section>
            {selectedInvoice.opening_balance !== "0.00" && (
              <div className="invoice-opening-summary">
                <div><strong>Saldo inicial informado</strong><span>Dívida que já existia ao começar a usar a SophIA; não representa uma compra nem uma despesa histórica.</span></div>
                <strong>{formatCurrency(selectedInvoice.opening_balance)}</strong>
              </div>
            )}
            <div className="invoice-columns">
              <section className="invoice-detail-group">
                <h4>Compras registradas</h4>
                {selectedInvoice.purchases.length > 0
                  ? selectedInvoice.purchases.map((item) => <div className="invoice-line" key={item.id}><span>{item.description}<small>{displayDate(item.occurred_at)}</small></span><strong>{formatCurrency(item.amount)}</strong></div>)
                  : <p className="invoice-detail-empty">Nenhuma compra detalhada neste ciclo.</p>}
              </section>
              <section className="invoice-detail-group">
                <h4>Pagamentos registrados</h4>
                {selectedInvoice.payments.length > 0
                  ? selectedInvoice.payments.map((item) => <div className="invoice-line" key={item.id}><span>{item.description}<small>{displayDate(item.occurred_at)}</small></span><strong>{formatCurrency(item.amount)}</strong></div>)
                  : <p className="invoice-detail-empty">Nenhum pagamento registrado neste ciclo.</p>}
              </section>
            </div>
            {selectedInvoice.outstanding !== "0.00" && (
              <form className="editor-form invoice-payment-form" onSubmit={payInvoice}>
                <div className="editor-heading"><h3>Registrar pagamento</h3><span className="form-note">Em aberto: {formatCurrency(selectedInvoice.outstanding)}</span></div>
                <div className="form-grid transaction-form-grid">
                  <label className="field-label">Conta pagadora<select onChange={(event) => setPaymentForm({ ...paymentForm, account_id: event.target.value })} required value={paymentForm.account_id}><option value="">Selecione</option>{activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>
                  <div className="field-label"><label htmlFor="invoice-payment-amount">Valor</label><CurrencyInput id="invoice-payment-amount" onChange={(value) => setPaymentForm({ ...paymentForm, amount: value })} placeholder="0,00" required value={paymentForm.amount} /></div>
                  <div className="field-label"><label htmlFor="invoice-payment-date">Data</label><CalendarDateInput id="invoice-payment-date" onChange={(value) => setPaymentForm({ ...paymentForm, occurred_at: value })} required value={paymentForm.occurred_at} /></div>
                </div>
                <div className="form-actions"><button className="primary-button compact-button" disabled={busy || activeAccounts.length === 0} type="submit">{busy ? "Salvando…" : "Registrar pagamento"}</button><span className="form-note">O pagamento reduz o saldo da conta sem repetir a despesa.</span></div>
              </form>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function EmptyState({ message, actionLabel, onAction }: { message: string; actionLabel?: string; onAction?: () => void }) {
  return <div className="empty-state"><span className="empty-mark" aria-hidden="true">↗</span><p>{message}</p>{actionLabel && onAction && <button className="empty-state-action" onClick={onAction} type="button">{actionLabel}<span aria-hidden="true">↗</span></button>}</div>;
}
