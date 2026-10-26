"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { apiRequest } from "@/lib/api";
import { formatCurrency, toDecimalString } from "@/lib/money";
import { useEditorScroll } from "@/lib/use-editor-scroll";
import { CurrencyInput } from "@/components/currency-input";
import { CalendarDateInput } from "@/components/calendar-date-input";
import { PaginationControls, usePagination } from "@/components/pagination";
import { useSophiaConfirmation } from "@/components/sophia-confirmation-dialog";
import type { FinanceFocusTarget } from "@/lib/finance-types";

type Account = { id: string; name: string; is_active: boolean };
type Category = { id: string; name: string; type: "INCOME" | "EXPENSE"; is_archived: boolean };
type CreditCard = {
  id: string;
  name: string;
  institution: string | null;
  credit_limit: string;
  closing_day: number;
  due_day: number;
  payment_account_id: string | null;
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
  installment_group_id?: string | null;
  installment_number?: number | null;
  installment_count?: number | null;
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
type BillingCyclePreview = Pick<CardInvoice, "period_start" | "period_end" | "closing_date" | "due_date">;
type UpcomingCardInvoice = Pick<
  CardInvoice,
  | "id"
  | "credit_card_id"
  | "credit_card_name"
  | "period_start"
  | "period_end"
  | "due_date"
  | "total"
  | "paid_amount"
  | "outstanding"
  | "status"
>;
type CardForm = {
  name: string;
  institution: string;
  credit_limit: string;
  closing_day: string;
  due_day: string;
  payment_account_id: string;
};
type Notice = { kind: "success" | "error"; message: string } | null;

const invoiceMonthFormatter = new Intl.DateTimeFormat("pt-BR", {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

function groupUpcomingInvoicesByDueMonth(invoices: UpcomingCardInvoice[]) {
  const groups = new Map<string, UpcomingCardInvoice[]>();
  for (const invoice of invoices) {
    const month = invoice.due_date.slice(0, 7);
    const group = groups.get(month) ?? [];
    group.push(invoice);
    groups.set(month, group);
  }

  return Array.from(groups, ([month, monthInvoices]) => ({
    month,
    label: invoiceMonthFormatter.format(new Date(`${month}-01T00:00:00.000Z`)),
    invoices: monthInvoices,
  }));
}

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

function displayDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function emptyCard(): CardForm {
  return { name: "", institution: "", credit_limit: "", closing_day: "13", due_day: "20", payment_account_id: "" };
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
  focusTarget,
  focusCardId,
  openPurchaseFormRequest,
  onPurchaseFormRequestHandled,
  onFinanceChanged,
}: {
  accounts: Account[];
  categories: Category[];
  focusTarget?: FinanceFocusTarget | null;
  focusCardId?: string | null;
  openPurchaseFormRequest: boolean;
  onPurchaseFormRequestHandled: () => void;
  onFinanceChanged: () => void;
}) {
  const [cards, setCards] = useState<CreditCard[]>([]);
  const [invoices, setInvoices] = useState<CardInvoice[]>([]);
  const [upcomingInvoices, setUpcomingInvoices] = useState<UpcomingCardInvoice[]>([]);
  const [selectedCardId, setSelectedCardId] = useState(focusCardId ?? "");
  const [selectedInvoiceId, setSelectedInvoiceId] = useState("");
  const [pendingInvoiceId, setPendingInvoiceId] = useState<string | null>(null);
  const [cardFormOpen, setCardFormOpen] = useState(false);
  const [cardEditingId, setCardEditingId] = useState<string | null>(null);
  const [cardForm, setCardForm] = useState<CardForm>(emptyCard);
  const [purchaseFormOpen, setPurchaseFormOpen] = useState(false);
  const [purchaseForm, setPurchaseForm] = useState({
    credit_card_id: "",
    category_id: "",
    description: "",
    amount: "",
    installment_count: "1",
    occurred_at: localDate(),
    notes: "",
  });
  const [paymentForm, setPaymentForm] = useState({ account_id: "", amount: "", occurred_at: localDate() });
  const [openingInvoiceFormOpen, setOpeningInvoiceFormOpen] = useState(false);
  const [openingInvoiceId, setOpeningInvoiceId] = useState<string | null>(null);
  const [openingInvoiceForm, setOpeningInvoiceForm] = useState({ due_month: "", amount: "" });
  const [openingInvoiceCycle, setOpeningInvoiceCycle] = useState<BillingCyclePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const invoiceDetailsRef = useRef<HTMLDivElement>(null);
  const invoiceCyclesHeadingRef = useRef<HTMLDivElement>(null);
  const { editorRef: cardEditorRef, scrollToEditor: scrollToCardEditor } = useEditorScroll<HTMLFormElement>();
  const { editorRef: purchaseEditorRef, scrollToEditor: scrollToPurchaseEditor } = useEditorScroll<HTMLFormElement>();
  const { editorRef: openingInvoiceFormRef, scrollToEditor: scrollToOpeningInvoiceEditor } = useEditorScroll<HTMLFormElement>();
  const initialCardFocusHandled = useRef(false);
  const { confirm, dialog: confirmationDialog } = useSophiaConfirmation();

  const activeCards = useMemo(() => cards.filter((card) => card.is_active), [cards]);
  const activeAccounts = useMemo(() => accounts.filter((account) => account.is_active), [accounts]);
  const expenseCategories = useMemo(
    () => categories.filter((category) => !category.is_archived && category.type === "EXPENSE"),
    [categories],
  );
  const selectedCard = cards.find((card) => card.id === selectedCardId) ?? null;
  const selectedInvoice = invoices.find((invoice) => invoice.id === selectedInvoiceId) ?? null;
  const orderedUpcomingInvoices = useMemo(
    () => [...upcomingInvoices].sort((left, right) =>
      left.due_date.localeCompare(right.due_date)
      || left.credit_card_name.localeCompare(right.credit_card_name, "pt-BR")
      || left.period_start.localeCompare(right.period_start)),
    [upcomingInvoices],
  );
  const cardsPagination = usePagination(cards, String(cards.length));
  const upcomingPagination = usePagination(orderedUpcomingInvoices, "upcoming-invoices");
  const invoicesPagination = usePagination(invoices, selectedCardId);
  const purchasePagination = usePagination(selectedInvoice?.purchases ?? [], selectedInvoiceId);
  const paymentPagination = usePagination(selectedInvoice?.payments ?? [], selectedInvoiceId);
  const upcomingInvoiceGroups = useMemo(
    () => groupUpcomingInvoicesByDueMonth(upcomingPagination.items),
    [upcomingPagination.items],
  );

  useEffect(() => {
    if (focusTarget?.source !== "CARD_INVOICE" || !focusTarget.credit_card_id) return;
    const card = cards.find((item) => item.id === focusTarget.credit_card_id);
    if (!card) return;
    if (selectedCardId !== card.id) {
      setSelectedCardId(card.id);
      setSelectedInvoiceId("");
      return;
    }
    const invoice = invoices.find((item) => item.id === focusTarget.id);
    if (!invoice) return;
    const invoiceIndex = invoices.findIndex((item) => item.id === invoice.id);
    const targetPage = Math.floor(invoiceIndex / invoicesPagination.pageSize) + 1;
    if (invoicesPagination.page !== targetPage) {
      invoicesPagination.setPage(targetPage);
    }
    setSelectedInvoiceId(invoice.id);
    const defaultAccountId = card.payment_account_id && activeAccounts.some((item) => item.id === card.payment_account_id)
      ? card.payment_account_id
      : activeAccounts.length === 1 ? activeAccounts[0]?.id ?? "" : "";
    setPaymentForm({ account_id: defaultAccountId, amount: invoice.outstanding, occurred_at: localDate() });
  }, [activeAccounts, cards, focusTarget, invoices, invoicesPagination.page, invoicesPagination.pageSize, invoicesPagination.setPage, selectedCardId]);

  useEffect(() => {
    if (!pendingInvoiceId) return;
    const invoice = invoices.find((item) => item.id === pendingInvoiceId);
    if (!invoice) return;
    const invoiceIndex = invoices.findIndex((item) => item.id === invoice.id);
    invoicesPagination.setPage(Math.floor(invoiceIndex / invoicesPagination.pageSize) + 1);
    const card = cards.find((item) => item.id === invoice.credit_card_id);
    setSelectedInvoiceId(invoice.id);
    const defaultAccountId = card?.payment_account_id && activeAccounts.some((item) => item.id === card.payment_account_id)
      ? card.payment_account_id
      : activeAccounts.length === 1 ? activeAccounts[0]?.id ?? "" : "";
    setPaymentForm({ account_id: defaultAccountId, amount: invoice.outstanding, occurred_at: localDate() });
    setPendingInvoiceId(null);
  }, [activeAccounts, cards, invoices, invoicesPagination.pageSize, invoicesPagination.setPage, pendingInvoiceId]);

  useEffect(() => {
    if (focusTarget?.source !== "CARD_INVOICE" || selectedInvoiceId !== focusTarget.id || !selectedInvoice) return;
    const frame = window.requestAnimationFrame(() => {
      invoiceDetailsRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      invoiceDetailsRef.current?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [focusTarget, selectedInvoice, selectedInvoiceId]);

  useEffect(() => {
    if (!openPurchaseFormRequest) return;
    setNotice(null);
    setPurchaseFormOpen(true);
    scrollToPurchaseEditor();
    onPurchaseFormRequestHandled();
  }, [onPurchaseFormRequestHandled, openPurchaseFormRequest, scrollToPurchaseEditor]);

  useEffect(() => {
    if (!selectedInvoiceId || focusTarget?.source === "CARD_INVOICE") return;
    const frame = window.requestAnimationFrame(() => {
      invoiceDetailsRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [focusTarget, selectedInvoiceId]);

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
    if (!focusCardId || initialCardFocusHandled.current || cards.length === 0) return;
    initialCardFocusHandled.current = true;
    if (!cards.some((card) => card.id === focusCardId)) return;
    setSelectedCardId(focusCardId);
    setSelectedInvoiceId("");
    const frame = window.requestAnimationFrame(() => {
      invoiceCyclesHeadingRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [cards, focusCardId]);

  useEffect(() => {
    void loadInvoices();
  }, [loadInvoices]);

  const loadUpcomingInvoices = useCallback(async () => {
    try {
      const rows = await apiRequest<UpcomingCardInvoice[]>("/api/cards/invoices/upcoming");
      setUpcomingInvoices(rows);
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível carregar as próximas faturas." });
    }
  }, []);

  useEffect(() => {
    void loadUpcomingInvoices();
  }, [loadUpcomingInvoices]);

  useEffect(() => {
    if (!openingInvoiceFormOpen || !selectedCardId || !openingInvoiceForm.due_month) {
      setOpeningInvoiceCycle(null);
      return;
    }
    let active = true;
    setOpeningInvoiceCycle(null);
    void apiRequest<BillingCyclePreview>(
      `/api/cards/${selectedCardId}/billing-cycle?due_month=${encodeURIComponent(openingInvoiceForm.due_month)}`,
    ).then((cycle) => {
      if (active) setOpeningInvoiceCycle(cycle);
    }).catch(() => {
      if (active) setOpeningInvoiceCycle(null);
    });
    return () => {
      active = false;
    };
  }, [openingInvoiceForm.due_month, openingInvoiceFormOpen, selectedCardId]);

  async function refresh(message: string) {
    setNotice({ kind: "success", message });
    await Promise.all([loadCards(), loadInvoices(), loadUpcomingInvoices()]);
    onFinanceChanged();
  }

  function openUpcomingInvoice(invoice: UpcomingCardInvoice) {
    setSelectedCardId(invoice.credit_card_id);
    setSelectedInvoiceId("");
    setPendingInvoiceId(invoice.id);
    document.getElementById("card-invoice-cycles")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function editOpeningInvoice(invoice: CardInvoice) {
    if (invoice.opening_balance === "0.00" || invoice.purchases.length > 0 || invoice.payments.length > 0) return;
    setSelectedCardId(invoice.credit_card_id);
    setSelectedInvoiceId("");
    setOpeningInvoiceId(invoice.id);
    setOpeningInvoiceForm({ due_month: invoice.due_date.slice(0, 7), amount: invoice.opening_balance });
    setOpeningInvoiceFormOpen(true);
    scrollToOpeningInvoiceEditor();
  }

  function editCard(card: CreditCard) {
    setCardEditingId(card.id);
    setCardForm({
      name: card.name,
      institution: card.institution ?? "",
      credit_limit: card.credit_limit,
      closing_day: String(card.closing_day),
      due_day: String(card.due_day),
      payment_account_id: card.payment_account_id ?? "",
    });
    setCardFormOpen(true);
    scrollToCardEditor();
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
        payment_account_id: cardForm.payment_account_id || null,
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

  async function deleteCard(card: CreditCard) {
    if (!(await confirm({
      title: "Excluir este cartão?",
      description: `O cartão ${card.name} será removido permanentemente.`,
      impact: "Antes, exclua as faturas vinculadas. As compras e os pagamentos registrados nelas também serão removidos e os saldos recalculados.",
      confirmLabel: "Excluir cartão",
    }))) return;
    setBusy(true);
    try {
      await apiRequest<void>(`/api/cards/${card.id}`, { method: "DELETE" });
      if (selectedCardId === card.id) setSelectedCardId("");
      await refresh("Cartão excluído.");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível excluir o cartão." });
    } finally {
      setBusy(false);
    }
  }

  async function deleteInvoice(invoice: CardInvoice | UpcomingCardInvoice) {
    const hasDetails = "purchases" in invoice;
    const purchaseCount = hasDetails ? invoice.purchases.length : null;
    const paymentCount = hasDetails ? invoice.payments.length : null;
    const purchaseText = purchaseCount === null
      ? "As compras vinculadas serão removidas"
      : `${purchaseCount} ${purchaseCount === 1 ? "compra vinculada será removida" : "compras vinculadas serão removidas"}`;
    const paymentText = paymentCount === null
      ? "os pagamentos registrados serão estornados do saldo das contas"
      : `${paymentCount} ${paymentCount === 1 ? "pagamento será estornado do saldo da conta" : "pagamentos serão estornados dos saldos das contas"}`;
    if (!(await confirm({
      title: "Excluir esta fatura?",
      description: `${invoice.credit_card_name}, vencimento ${displayDate(invoice.due_date)}, total ${formatCurrency(invoice.total)}.`,
      impact: `${purchaseText}; ${paymentText}. Os saldos e o limite do cartão serão recalculados.`,
      confirmLabel: "Excluir fatura",
    }))) return;
    setBusy(true);
    try {
      await apiRequest<void>(`/api/invoices/${invoice.id}`, { method: "DELETE" });
      setSelectedInvoiceId((current) => current === invoice.id ? "" : current);
      await refresh("Fatura e lançamentos vinculados excluídos.");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível excluir a fatura." });
    } finally {
      setBusy(false);
    }
  }

  async function createPurchase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      const installmentCount = Number(purchaseForm.installment_count);
      const commonPayload = {
        credit_card_id: purchaseForm.credit_card_id,
        category_id: purchaseForm.category_id,
        description: purchaseForm.description,
        occurred_at: purchaseForm.occurred_at,
        notes: purchaseForm.notes || null,
      };
      if (installmentCount > 1) {
        await apiRequest("/api/card-purchase-plans", {
          method: "POST",
          body: JSON.stringify({
            ...commonPayload,
            total_amount: toDecimalString(purchaseForm.amount),
            installment_count: installmentCount,
          }),
        });
      } else {
        await apiRequest("/api/card-purchases", {
          method: "POST",
          body: JSON.stringify({
            ...commonPayload,
            amount: toDecimalString(purchaseForm.amount),
          }),
        });
      }
      setPurchaseForm({ ...purchaseForm, description: "", amount: "", installment_count: "1", notes: "" });
      setPurchaseFormOpen(false);
      await refresh(installmentCount > 1
        ? `Compra parcelada em ${installmentCount} vezes registrada nas faturas correspondentes. O saldo das contas não mudou.`
        : "Compra registrada na fatura. O saldo das contas não mudou.");
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
        openingInvoiceId
          ? `/api/invoices/${openingInvoiceId}/opening-balance`
          : `/api/cards/${selectedCard.id}/invoices/opening-balance`,
        {
          method: "PUT",
          body: JSON.stringify({
            due_month: openingInvoiceForm.due_month,
            amount: toDecimalString(openingInvoiceForm.amount),
          }),
        },
      );
      setSelectedCardId(selectedCard.id);
      setSelectedInvoiceId(invoice.id);
      const wasEditing = openingInvoiceId !== null;
      setOpeningInvoiceId(null);
      setOpeningInvoiceForm({ due_month: "", amount: "" });
      setOpeningInvoiceFormOpen(false);
      await refresh(wasEditing
        ? "Ciclo e saldo inicial da fatura ajustados. Compras e pagamentos não foram alterados."
        : "Saldo da fatura importado. Ele não foi lançado como despesa.");
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
          <button className="primary-button compact-button" onClick={() => { setCardEditingId(null); setCardForm(emptyCard()); setCardFormOpen(true); scrollToCardEditor(); }} type="button">＋ Novo cartão</button>
        </div>
        {cardFormOpen && (
          <form className="editor-form" data-scroll-editor="true" onSubmit={saveCard} ref={cardEditorRef}>
            <div className="editor-heading"><h3 data-editor-heading tabIndex={-1}>{cardEditingId ? "Editar cartão" : "Adicionar cartão"}</h3><button className="text-button" onClick={() => setCardFormOpen(false)} type="button">Fechar</button></div>
            <div className="form-grid transaction-form-grid">
              <label className="field-label">Nome<input maxLength={100} onChange={(event) => setCardForm({ ...cardForm, name: event.target.value })} required value={cardForm.name} /></label>
              <label className="field-label">Instituição<input maxLength={100} onChange={(event) => setCardForm({ ...cardForm, institution: event.target.value })} value={cardForm.institution} /></label>
              <div className="field-label"><label htmlFor="credit-card-limit">Limite</label><CurrencyInput id="credit-card-limit" onChange={(value) => setCardForm({ ...cardForm, credit_limit: value })} placeholder="0,00" required value={cardForm.credit_limit} /></div>
              <label className="field-label">Dia de fechamento<input max={31} min={1} onChange={(event) => setCardForm({ ...cardForm, closing_day: event.target.value })} required type="number" value={cardForm.closing_day} /></label>
              <label className="field-label">Dia de vencimento<input max={31} min={1} onChange={(event) => setCardForm({ ...cardForm, due_day: event.target.value })} required type="number" value={cardForm.due_day} /></label>
              <label className="field-label">Conta usada para pagar a fatura (opcional)<select onChange={(event) => setCardForm({ ...cardForm, payment_account_id: event.target.value })} value={cardForm.payment_account_id}><option value="">Ainda não definida</option>{activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select><small>Usada somente para estimar o saldo previsto. O pagamento continua dependendo de você registrá-lo.</small></label>
            </div>
            <div className="form-actions"><button className="primary-button compact-button" disabled={busy} type="submit">{busy ? "Salvando…" : "Salvar cartão"}</button><span className="form-note">Quando o dia não existe no mês, usamos o último dia daquele mês.</span></div>
          </form>
        )}
        {cards.length === 0 ? <EmptyState actionLabel="Cadastrar primeiro cartão" message="Cadastre um cartão para acompanhar compras e faturas." onAction={() => { setCardEditingId(null); setCardForm(emptyCard()); setCardFormOpen(true); scrollToCardEditor(); }} /> : (
          <><div className="table-wrap"><table className="data-table"><thead><tr><th>Cartão</th><th>Limite</th><th>Utilizado</th><th>Disponível</th><th>Próximo vencimento</th><th>Situação</th><th aria-label="Ações" /></tr></thead><tbody>
            {cardsPagination.items.map((card) => <tr key={card.id}><td data-label="Cartão"><strong className="cell-primary">{card.name}</strong><small className="cell-secondary">{card.institution ?? "Cartão de crédito"} · fecha {card.closing_day} · vence {card.due_day}</small></td><td className="table-money" data-label="Limite">{formatCurrency(card.credit_limit)}</td><td className="table-money" data-label="Utilizado">{formatCurrency(card.used_limit)}</td><td className="table-money" data-label="Disponível">{formatCurrency(card.available_limit)}</td><td data-label="Próximo vencimento">{card.next_due_date ? displayDate(card.next_due_date) : "—"}</td><td data-label="Situação"><span className={card.is_active ? "state-pill active" : "state-pill archived"}>{card.is_active ? "Ativo" : "Arquivado"}</span></td><td className="row-actions" data-label="Ações">{card.is_active && <><button className="table-action" onClick={() => editCard(card)} type="button">Editar</button><button className="table-action danger-action" disabled={busy} onClick={() => void archiveCard(card)} type="button">Arquivar</button></>}<button className="table-action danger-action" disabled={busy} onClick={() => void deleteCard(card)} type="button">Excluir</button></td></tr>)}
          </tbody></table></div><PaginationControls end={cardsPagination.end} label="Paginação dos cartões" onPageChange={cardsPagination.setPage} page={cardsPagination.page} pageCount={cardsPagination.pageCount} start={cardsPagination.start} total={cardsPagination.total} /></>
        )}
      </section>

      <section className="surface-card data-card">
        <div className="surface-heading">
          <div><p className="eyebrow">Consumo</p><h2>Compras no cartão</h2></div>
          <button className="primary-button compact-button" disabled={activeCards.length === 0} onClick={() => { setPurchaseForm({ ...purchaseForm, credit_card_id: purchaseForm.credit_card_id || (activeCards.length === 1 ? activeCards[0]?.id ?? "" : ""), category_id: purchaseForm.category_id || (expenseCategories.length === 1 ? expenseCategories[0]?.id ?? "" : "") }); setPurchaseFormOpen(true); scrollToPurchaseEditor(); }} type="button">＋ Nova compra</button>
        </div>
        {purchaseFormOpen && (
          <form className="editor-form" data-scroll-editor="true" onSubmit={createPurchase} ref={purchaseEditorRef}>
            <div className="editor-heading"><h3 data-editor-heading tabIndex={-1}>Registrar compra</h3><button className="text-button" onClick={() => setPurchaseFormOpen(false)} type="button">Fechar</button></div>
            <div className="form-grid transaction-form-grid">
              <label className="field-label">Cartão<select onChange={(event) => setPurchaseForm({ ...purchaseForm, credit_card_id: event.target.value })} required value={purchaseForm.credit_card_id}><option value="">Selecione</option>{activeCards.map((card) => <option key={card.id} value={card.id}>{card.name}</option>)}</select></label>
              <div className="field-label"><label htmlFor="card-purchase-date">Data</label><CalendarDateInput id="card-purchase-date" onChange={(value) => setPurchaseForm({ ...purchaseForm, occurred_at: value })} required value={purchaseForm.occurred_at} /></div>
              <label className="field-label">Categoria<select onChange={(event) => setPurchaseForm({ ...purchaseForm, category_id: event.target.value })} required value={purchaseForm.category_id}><option value="">Selecione</option>{expenseCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
              <label className="field-label">Descrição<input maxLength={200} onChange={(event) => setPurchaseForm({ ...purchaseForm, description: event.target.value })} required value={purchaseForm.description} /></label>
              <div className="field-label"><label htmlFor="card-purchase-amount">{Number(purchaseForm.installment_count) > 1 ? "Valor total" : "Valor"}</label><CurrencyInput id="card-purchase-amount" onChange={(value) => setPurchaseForm({ ...purchaseForm, amount: value })} placeholder="0,00" required value={purchaseForm.amount} /></div>
              <label className="field-label">Parcelas<select onChange={(event) => setPurchaseForm({ ...purchaseForm, installment_count: event.target.value })} required value={purchaseForm.installment_count}>{Array.from({ length: 36 }, (_, index) => index + 1).map((count) => <option key={count} value={count}>{count === 1 ? "À vista" : `${count} parcelas`}</option>)}</select></label>
              {Number(purchaseForm.installment_count) > 1 && <p className="form-note full-width-field">O total será distribuído entre as faturas seguintes; os centavos restantes ficam nas primeiras parcelas.</p>}
              <label className="field-label full-width-field">Observações<textarea maxLength={2000} onChange={(event) => setPurchaseForm({ ...purchaseForm, notes: event.target.value })} rows={2} value={purchaseForm.notes} /></label>
            </div>
            {(activeCards.length === 0 || expenseCategories.length === 0) && <p className="form-helper">Cadastre um cartão ativo e uma categoria de despesa antes de registrar compras.</p>}
            <div className="form-actions"><button className="primary-button compact-button" disabled={busy || activeCards.length === 0 || expenseCategories.length === 0} type="submit">{busy ? "Salvando…" : "Registrar compra"}</button><span className="form-note">A compra conta como despesa e aumenta a fatura.</span></div>
          </form>
        )}
      </section>

      <section className="surface-card data-card" id="card-invoice-cycles">
        <div className="surface-heading"><div><p className="eyebrow">Ciclos mensais</p><h2>Faturas</h2></div></div>
        <section aria-label="Próximas faturas de todos os cartões" className="upcoming-invoices">
          <div className="editor-heading"><div><h3>Próximas faturas de todos os cartões</h3><p className="form-note">Visão consolidada, agrupada por vencimento mais próximo.</p></div><span className="state-pill active">{upcomingInvoices.length}</span></div>
          {upcomingInvoices.length === 0 ? <p className="invoice-detail-empty">Nenhuma fatura em aberto cadastrada.</p> : (
            <>
              <div className="upcoming-invoice-groups" id="upcoming-invoice-groups">
                {upcomingInvoiceGroups.map((group) => <section aria-labelledby={`upcoming-invoice-month-${group.month}`} className="upcoming-invoice-month-group" key={group.month}>
                  <div className="upcoming-invoice-month-heading"><h4 id={`upcoming-invoice-month-${group.month}`}>{group.label}</h4><span>{group.invoices.length} {group.invoices.length === 1 ? "fatura" : "faturas"}</span></div>
                  <div className="upcoming-invoice-list">
                    {group.invoices.map((invoice) => <article className="upcoming-invoice-row" key={invoice.id}>
                      <div className="upcoming-invoice-due"><span>Vencimento</span><strong>{displayDate(invoice.due_date)}</strong></div>
                      <div className="upcoming-invoice-card"><strong>{invoice.credit_card_name}</strong><span>Ciclo {displayDate(invoice.period_start)} – {displayDate(invoice.period_end)}</span></div>
                      <div className="upcoming-invoice-amount"><span>Em aberto</span><strong>{formatCurrency(invoice.outstanding)}</strong></div>
                      <span className={`state-pill ${invoice.status === "OVERDUE" ? "overdue" : "active"}`}>{statusLabel(invoice.status)}</span>
                      <div className="upcoming-invoice-actions"><button className="table-action" onClick={() => openUpcomingInvoice(invoice)} type="button">Detalhes / pagar</button><button className="table-action danger-action" disabled={busy} onClick={() => void deleteInvoice(invoice)} type="button">Excluir fatura</button></div>
                    </article>)}
                  </div>
                </section>)}
              </div>
              <PaginationControls end={upcomingPagination.end} label="Paginação das próximas faturas" onPageChange={upcomingPagination.setPage} page={upcomingPagination.page} pageCount={upcomingPagination.pageCount} start={upcomingPagination.start} total={upcomingPagination.total} />
            </>
          )}
        </section>
        <div className="editor-heading invoice-card-cycle-heading" ref={invoiceCyclesHeadingRef}>
          <div><p className="eyebrow">Ciclos do cartão</p><h3>Faturas de {selectedCard?.name ?? "um cartão"}</h3><p className="form-note">Escolha um cartão para consultar seus ciclos, valores pagos e saldo em aberto.</p></div>
          <div className="invoice-heading-actions">
            <label className="month-picker">Cartão para visualizar<select aria-label="Cartão para visualizar" onChange={(event) => { setSelectedCardId(event.target.value); setSelectedInvoiceId(""); }} value={selectedCardId}><option value="">Selecione</option>{cards.map((card) => <option key={card.id} value={card.id}>{card.name}{card.is_active ? "" : " (arquivado)"}</option>)}</select></label>
            <button className="secondary-button compact-button" disabled={activeCards.length === 0} onClick={() => { const card = activeCards.find((item) => item.id === selectedCardId) ?? activeCards[0]; if (card) setSelectedCardId(card.id); setOpeningInvoiceId(null); setOpeningInvoiceForm({ due_month: "", amount: "" }); setOpeningInvoiceFormOpen(true); scrollToOpeningInvoiceEditor(); }} type="button">＋ Registrar fatura existente</button>
          </div>
        </div>
        {openingInvoiceFormOpen && (
          <form className="editor-form opening-invoice-form" data-scroll-editor="true" onSubmit={(event) => void saveOpeningInvoice(event)} ref={openingInvoiceFormRef}>
            <div className="editor-heading"><div><h3 data-editor-heading tabIndex={-1}>{openingInvoiceId ? "Ajustar ciclo da fatura" : "Saldo de uma fatura existente"}</h3><p className="form-note">Informe o total em aberto e o mês em que a fatura vence. A SophIA associa automaticamente o ciclo pelo fechamento do cartão.</p></div><button aria-label="Fechar formulário" className="text-button" onClick={() => { setOpeningInvoiceFormOpen(false); setOpeningInvoiceId(null); }} type="button">Fechar</button></div>
            <div className="form-grid transaction-form-grid">
              <label className="field-label">Cartão<select onChange={(event) => setSelectedCardId(event.target.value)} required value={selectedCardId}><option value="">Selecione</option>{activeCards.map((card) => <option key={card.id} value={card.id}>{card.name}</option>)}</select></label>
              <label className="field-label">Mês do vencimento<input onChange={(event) => setOpeningInvoiceForm({ ...openingInvoiceForm, due_month: event.target.value })} required type="month" value={openingInvoiceForm.due_month} /><small>Ex.: a fatura que vence em novembro pode fechar em outubro, conforme o cartão.</small></label>
              <div className="field-label"><label htmlFor="invoice-opening-amount">Saldo da fatura</label><CurrencyInput id="invoice-opening-amount" onChange={(value) => setOpeningInvoiceForm({ ...openingInvoiceForm, amount: value })} placeholder="0,00" required value={openingInvoiceForm.amount} /></div>
            </div>
            {openingInvoiceCycle && <p className="form-note opening-invoice-cycle-preview">Ciclo {displayDate(openingInvoiceCycle.period_start)}–{displayDate(openingInvoiceCycle.period_end)} · fechamento {displayDate(openingInvoiceCycle.closing_date)} · vencimento {displayDate(openingInvoiceCycle.due_date)}</p>}
            <div className="form-actions"><button className="primary-button compact-button" disabled={busy || !selectedCardId} type="submit">{busy ? "Salvando…" : openingInvoiceId ? "Salvar ajuste" : "Registrar saldo"}</button><span className="form-note">O pagamento poderá ser registrado depois e reduzirá o saldo da conta selecionada.</span></div>
          </form>
        )}
        {invoices.length === 0 ? <EmptyState actionLabel={cards.length === 0 ? "Cadastrar cartão" : "Registrar fatura existente"} message={cards.length === 0 ? "Cadastre um cartão para acompanhar suas faturas." : "Informe o saldo de uma fatura que já existe ou registre a primeira compra no cartão."} onAction={() => {
          if (cards.length === 0) {
            setCardEditingId(null);
            setCardForm(emptyCard());
            setCardFormOpen(true);
            scrollToCardEditor();
          } else {
            const card = activeCards.find((item) => item.id === selectedCardId) ?? activeCards[0];
            if (card) setSelectedCardId(card.id);
            setOpeningInvoiceId(null);
            setOpeningInvoiceForm({ due_month: "", amount: "" });
            setOpeningInvoiceFormOpen(true);
            scrollToOpeningInvoiceEditor();
          }
        }} /> : (
          <><div className="table-wrap"><table className="data-table"><thead><tr><th>Ciclo</th><th>Fechamento</th><th>Vencimento</th><th>Total</th><th>Pago</th><th>Em aberto</th><th>Status</th><th /></tr></thead><tbody>
            {invoicesPagination.items.map((invoice) => <tr className={focusTarget?.source === "CARD_INVOICE" && focusTarget.id === invoice.id ? "notification-target" : undefined} key={invoice.id}><td data-label="Ciclo">{displayDate(invoice.period_start)} – {displayDate(invoice.period_end)}</td><td data-label="Fechamento">{displayDate(invoice.closing_date)}</td><td data-label="Vencimento">{displayDate(invoice.due_date)}</td><td className="table-money" data-label="Total">{formatCurrency(invoice.total)}</td><td data-label="Pago">{formatCurrency(invoice.paid_amount)}</td><td data-label="Em aberto">{formatCurrency(invoice.outstanding)}</td><td data-label="Status"><span className={`state-pill ${invoice.status === "PAID" ? "active" : "archived"}`}>{statusLabel(invoice.status)}</span></td><td className="row-actions" data-label="Ações">{invoice.opening_balance !== "0.00" && invoice.purchases.length === 0 && invoice.payments.length === 0 && <button className="table-action" disabled={busy} onClick={() => editOpeningInvoice(invoice)} type="button">Corrigir ciclo</button>}<button className="table-action" onClick={() => { setSelectedInvoiceId(invoice.id); setPaymentForm({ account_id: activeAccounts.length === 1 ? activeAccounts[0]?.id ?? "" : "", amount: invoice.outstanding, occurred_at: localDate() }); }} type="button">Detalhes / pagar</button><button className="table-action danger-action" disabled={busy} onClick={() => void deleteInvoice(invoice)} type="button">Excluir</button></td></tr>)}
          </tbody></table></div><PaginationControls end={invoicesPagination.end} label="Paginação das faturas do cartão" onPageChange={invoicesPagination.setPage} page={invoicesPagination.page} pageCount={invoicesPagination.pageCount} start={invoicesPagination.start} total={invoicesPagination.total} /></>
        )}
        {selectedInvoice && (
          <section aria-label="Detalhes da fatura e registro de pagamento" className="invoice-details" ref={invoiceDetailsRef} tabIndex={-1}>
            <div className="surface-heading invoice-details-heading">
              <div className="invoice-details-title">
                <p className="eyebrow">{selectedInvoice.credit_card_name}</p>
                <h3>Detalhes da fatura</h3>
                <p className="invoice-details-meta">Ciclo {displayDate(selectedInvoice.period_start)} a {displayDate(selectedInvoice.period_end)} · vence em {displayDate(selectedInvoice.due_date)}</p>
              </div>
              <div className="invoice-details-actions">
                <span className={`state-pill ${selectedInvoice.status === "PAID" ? "active" : "archived"}`}>{statusLabel(selectedInvoice.status)}</span>
                <button className="table-action danger-action" disabled={busy} onClick={() => void deleteInvoice(selectedInvoice)} type="button">Excluir fatura</button>
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
                  ? <>{purchasePagination.items.map((item) => <div className="invoice-line" key={item.id}><span>{item.description}<small>{displayDate(item.occurred_at)}{item.installment_number && item.installment_count ? ` · Parcela ${item.installment_number} de ${item.installment_count}` : ""}</small></span><strong>{formatCurrency(item.amount)}</strong></div>)}<PaginationControls end={purchasePagination.end} label="Paginação das compras da fatura" onPageChange={purchasePagination.setPage} page={purchasePagination.page} pageCount={purchasePagination.pageCount} start={purchasePagination.start} total={purchasePagination.total} /></>
                  : <p className="invoice-detail-empty">Nenhuma compra detalhada neste ciclo.</p>}
              </section>
              <section className="invoice-detail-group">
                <h4>Pagamentos registrados</h4>
                {selectedInvoice.payments.length > 0
                  ? <>{paymentPagination.items.map((item) => <div className="invoice-line" key={item.id}><span>{item.description}<small>{displayDate(item.occurred_at)}</small></span><strong>{formatCurrency(item.amount)}</strong></div>)}<PaginationControls end={paymentPagination.end} label="Paginação dos pagamentos da fatura" onPageChange={paymentPagination.setPage} page={paymentPagination.page} pageCount={paymentPagination.pageCount} start={paymentPagination.start} total={paymentPagination.total} /></>
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
          </section>
        )}
      </section>
      {confirmationDialog}
    </div>
  );
}

function EmptyState({ message, actionLabel, onAction }: { message: string; actionLabel?: string; onAction?: () => void }) {
  return <div className="empty-state"><span className="empty-mark" aria-hidden="true">↗</span><p>{message}</p>{actionLabel && onAction && <button className="empty-state-action" onClick={onAction} type="button">{actionLabel}<span aria-hidden="true">↗</span></button>}</div>;
}
