"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowDownLeft,
  ArrowLeftRight,
  ArrowUpRight,
  CreditCard,
  Landmark,
  LayoutDashboard,
  Plus,
  ReceiptText,
  Repeat2,
  Tags,
  type LucideIcon,
} from "lucide-react";

import { ApiError, apiRequest } from "@/lib/api";
import { formatCurrency, toDecimalString } from "@/lib/money";
import type { FinanceFocusTarget } from "@/lib/finance-types";
import { CurrencyInput } from "@/components/currency-input";
import { CalendarDateInput } from "@/components/calendar-date-input";
import { CalendarMonthInput } from "@/components/calendar-month-input";
import { CreditCardWorkspace } from "@/components/credit-card-workspace";
import { TransactionImport } from "@/components/transaction-import";
import { RecurrenceWorkspace } from "@/components/recurrence-workspace";
import { BrandMark } from "@/components/brand-mark";
import { useSophiaConfirmation } from "@/components/sophia-confirmation-dialog";
import { PaginationControls, usePagination } from "@/components/pagination";

type Section = "overview" | "transactions" | "accounts" | "categories" | "cards" | "recurrences";
type AccountType = "CHECKING" | "SAVINGS" | "CASH" | "OTHER";
type MovementType = "INCOME" | "EXPENSE";
type FinancialTransactionType = MovementType | "TRANSFER" | "CARD_PURCHASE" | "CARD_PAYMENT";

type Account = {
  id: string;
  name: string;
  type: AccountType;
  currency: "BRL";
  opening_balance: string | null;
  opening_balance_date: string | null;
  is_active: boolean;
  balance: string | null;
};

type Category = {
  id: string;
  name: string;
  type: MovementType;
  is_archived: boolean;
};

type Transaction = {
  id: string;
  account_id: string | null;
  category_id: string | null;
  category_name: string | null;
  source_account_id: string | null;
  destination_account_id: string | null;
  invoice_id: string | null;
  credit_card_id: string | null;
  credit_card_name: string | null;
  type: FinancialTransactionType;
  source: "MANUAL";
  status: "CONFIRMED";
  description: string;
  amount: string;
  occurred_at: string;
  notes: string | null;
};

type Dashboard = {
  as_of: string;
  period_start: string;
  period_end: string;
  checking_balance: string | null;
  incomplete_checking_account_count: number;
  account_type_balances: { account_type: AccountType; balance: string | null; projected_balance: string | null; account_count: number; incomplete_account_count: number }[];
  monthly_income: string;
  monthly_expenses: string;
  monthly_result: string;
  expenses_by_category: { category_id: string; category_name: string; amount: string }[];
  cards: {
    id: string;
    name: string;
    credit_limit: string;
    used_limit: string;
    available_limit: string;
    next_due_date: string | null;
  }[];
  recent_transactions: Transaction[];
  forecast_start: string;
  forecast_end: string;
  forecast_payables_total: string;
  forecast_overdue_total: string;
  forecast_next_7_days_total: string;
  forecast_rest_of_month_total: string;
  forecast_income_total: string;
  forecast_unassigned_invoice_total: string;
  forecast_items: { id: string; source: "RECURRENCE" | "COMMITMENT" | "CARD_INVOICE"; credit_card_id: string | null; description: string; type: MovementType; due_date: string; amount: string; account_type: AccountType | null; account_name: string | null; card_name: string | null; status: "OVERDUE" | "DUE_SOON" | "PLANNED" }[];
};

type AccountForm = {
  name: string;
  type: AccountType;
  opening_balance: string;
  opening_balance_date: string;
};

type TransactionForm = {
  account_id: string;
  category_id: string;
  type: MovementType;
  description: string;
  amount: string;
  occurred_at: string;
  notes: string;
};

type TransferForm = {
  source_account_id: string;
  destination_account_id: string;
  amount: string;
  occurred_at: string;
  notes: string;
};

type TransactionFilters = {
  start_date: string;
  end_date: string;
  account_id: string;
  category_id: string;
  type: "" | FinancialTransactionType;
  q: string;
};

type Notice = { kind: "success" | "error"; message: string } | null;

const FINANCE_NAV_ITEMS: { section: Section; label: string; icon: LucideIcon }[] = [
  { section: "overview", label: "Visão geral", icon: LayoutDashboard },
  { section: "transactions", label: "Lançamentos", icon: ReceiptText },
  { section: "accounts", label: "Contas", icon: Landmark },
  { section: "categories", label: "Categorias", icon: Tags },
  { section: "cards", label: "Cartões", icon: CreditCard },
  { section: "recurrences", label: "Programados", icon: Repeat2 },
];

function dateInSaoPaulo(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "America/Sao_Paulo",
    year: "numeric",
  }).formatToParts(new Date());
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function monthInSaoPaulo(): string {
  return dateInSaoPaulo().slice(0, 7);
}

function displayMonth(value: string): string {
  const [year, month] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, 15, 12));
  return new Intl.DateTimeFormat("pt-BR", {
    month: "long",
    timeZone: "America/Sao_Paulo",
    year: "numeric",
  }).format(date);
}

function displayDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function accountTypeLabel(value: AccountType): string {
  const labels: Record<AccountType, string> = {
    CHECKING: "Conta corrente",
    SAVINGS: "Poupança",
    CASH: "Dinheiro",
    OTHER: "Outra",
  };
  return labels[value];
}

function projectedCheckingLabel(dashboard: Dashboard): string {
  const projected = dashboard.account_type_balances.find((group) => group.account_type === "CHECKING")?.projected_balance;
  return projected === null || projected === undefined ? "Indisponível" : formatCurrency(projected);
}

function financialTransactionLabel(value: FinancialTransactionType): string {
  const labels: Record<FinancialTransactionType, string> = {
    INCOME: "Receita",
    EXPENSE: "Despesa",
    TRANSFER: "Transferência",
    CARD_PURCHASE: "Compra no cartão",
    CARD_PAYMENT: "Pagamento de fatura",
  };
  return labels[value];
}

function financialAmountSign(value: FinancialTransactionType): string {
  if (value === "INCOME") return "+";
  if (value === "EXPENSE" || value === "CARD_PURCHASE" || value === "CARD_PAYMENT") return "−";
  return "";
}

function isEditableTransaction(
  transaction: Transaction,
): transaction is Transaction & { type: MovementType } {
  return transaction.type === "INCOME" || transaction.type === "EXPENSE";
}

function transactionContext(transaction: Transaction, accounts: Account[]): string {
  const accountName = (id: string | null) =>
    accounts.find((account) => account.id === id)?.name ?? "Conta arquivada";
  if (transaction.type === "TRANSFER") {
    return `${accountName(transaction.source_account_id)} → ${accountName(transaction.destination_account_id)}`;
  }
  if (transaction.type === "CARD_PURCHASE") {
    return [transaction.credit_card_name, transaction.category_name].filter(Boolean).join(" · ");
  }
  if (transaction.type === "CARD_PAYMENT") {
    return `${transaction.credit_card_name ?? "Cartão"} · ${accountName(transaction.account_id)}`;
  }
  return [transaction.category_name, accountName(transaction.account_id)].filter(Boolean).join(" · ");
}

function emptyAccount(): AccountForm {
  return {
    name: "",
    type: "CHECKING",
    opening_balance: "",
    opening_balance_date: dateInSaoPaulo(),
  };
}

function emptyTransaction(): TransactionForm {
  return {
    account_id: "",
    category_id: "",
    type: "EXPENSE",
    description: "",
    amount: "",
    occurred_at: dateInSaoPaulo(),
    notes: "",
  };
}

function emptyTransfer(): TransferForm {
  return {
    source_account_id: "",
    destination_account_id: "",
    amount: "",
    occurred_at: dateInSaoPaulo(),
    notes: "",
  };
}

function emptyFilters(): TransactionFilters {
  return { start_date: "", end_date: "", account_id: "", category_id: "", type: "", q: "" };
}

export function FinanceWorkspace({
  displayName,
  onLogout,
  onOpenAssistant,
  embedded = false,
  initialSection = "overview",
  focusTarget = null,
}: {
  displayName: string;
  onLogout: () => void;
  onOpenAssistant?: (prompt: string) => void;
  embedded?: boolean;
  initialSection?: Section;
  focusTarget?: FinanceFocusTarget | null;
}) {
  const [section, setSection] = useState<Section>(initialSection);
  const [month, setMonth] = useState(monthInSaoPaulo);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [appliedFilters, setAppliedFilters] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  const { confirm, dialog: confirmationDialog } = useSophiaConfirmation();

  const [accountFormOpen, setAccountFormOpen] = useState(false);
  const [accountEditingId, setAccountEditingId] = useState<string | null>(null);
  const [accountForm, setAccountForm] = useState<AccountForm>(emptyAccount);
  const [returnToTransactionsAfterAccount, setReturnToTransactionsAfterAccount] = useState(false);
  const [categoryFormOpen, setCategoryFormOpen] = useState(false);
  const [categoryEditingId, setCategoryEditingId] = useState<string | null>(null);
  const [categoryName, setCategoryName] = useState("");
  const [categoryType, setCategoryType] = useState<MovementType>("EXPENSE");
  const [returnToTransactionsAfterCategory, setReturnToTransactionsAfterCategory] = useState(false);
  const [transactionFormOpen, setTransactionFormOpen] = useState(false);
  const [transactionEditingId, setTransactionEditingId] = useState<string | null>(null);
  const [transactionForm, setTransactionForm] = useState<TransactionForm>(emptyTransaction);
  const [transferFormOpen, setTransferFormOpen] = useState(false);
  const [transferForm, setTransferForm] = useState<TransferForm>(emptyTransfer);
  const [filters, setFilters] = useState<TransactionFilters>(emptyFilters);
  const loadVersion = useRef(0);

  const loadFinance = useCallback(async () => {
    const version = loadVersion.current + 1;
    loadVersion.current = version;
    setLoading(true);
    const [year, selectedMonth] = month.split("-").map(Number);
    const transactionPath = appliedFilters
      ? `/api/transactions?${appliedFilters}`
      : "/api/transactions";

    try {
      const [accountRows, categoryRows, transactionRows, summary] = await Promise.all([
        apiRequest<Account[]>("/api/accounts?include_archived=true"),
        apiRequest<Category[]>("/api/categories?include_archived=true"),
        apiRequest<Transaction[]>(transactionPath),
        apiRequest<Dashboard>(`/api/dashboard/summary?year=${year}&month=${selectedMonth}`),
      ]);
      if (version !== loadVersion.current) return;
      setAccounts(accountRows);
      setCategories(categoryRows);
      setTransactions(transactionRows);
      setDashboard(summary);
    } catch (error) {
      if (version !== loadVersion.current) return;
      if (error instanceof ApiError && error.status === 401) {
        window.location.reload();
        return;
      }
      setNotice({
        kind: "error",
        message: error instanceof Error ? error.message : "Não foi possível carregar os dados.",
      });
    } finally {
      if (version === loadVersion.current) setLoading(false);
    }
  }, [appliedFilters, month]);

  useEffect(() => {
    void loadFinance();
  }, [loadFinance]);

  function refreshAfterMutation(message: string) {
    setNotice({ kind: "success", message });
    void loadFinance();
  }

  async function saveAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNotice(null);
    try {
      const hasOpeningBalance = accountForm.opening_balance.trim().length > 0;
      const payload = {
        ...accountForm,
        opening_balance: hasOpeningBalance ? toDecimalString(accountForm.opening_balance) : null,
        opening_balance_date: hasOpeningBalance ? accountForm.opening_balance_date : null,
      };
      let savedAccount: Account;
      if (accountEditingId) {
        savedAccount = await apiRequest<Account>(`/api/accounts/${accountEditingId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        savedAccount = await apiRequest<Account>("/api/accounts", { method: "POST", body: JSON.stringify(payload) });
      }
      const returnToTransaction = returnToTransactionsAfterAccount && !accountEditingId;
      setAccountForm(emptyAccount());
      setAccountEditingId(null);
      setAccountFormOpen(false);
      if (returnToTransaction) {
        setTransactionForm((current) => ({ ...current, account_id: savedAccount.id }));
        setTransactionFormOpen(true);
        setReturnToTransactionsAfterAccount(false);
        setSection("transactions");
      }
      refreshAfterMutation(accountEditingId ? "Conta atualizada." : "Conta criada.");
    } catch (error) {
      setNotice({
        kind: "error",
        message: error instanceof Error ? error.message : "Não foi possível salvar a conta.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function archiveAccount(account: Account) {
    if (account.balance === null) {
      setNotice({ kind: "error", message: "Informe o saldo inicial e a data-base antes de arquivar esta conta." });
      return;
    }
    if (account.balance !== "0.00") {
      setNotice({ kind: "error", message: `Transfira ou concilie o saldo de ${formatCurrency(account.balance)} até R$ 0,00 antes de arquivar esta conta.` });
      return;
    }
    if (!window.confirm(`Arquivar a conta “${account.name}” com saldo zerado?`)) return;
    setBusy(true);
    try {
      await apiRequest<Account>(`/api/accounts/${account.id}/archive`, { method: "POST" });
      refreshAfterMutation("Conta arquivada. O histórico permanece salvo.");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Falha ao arquivar." });
    } finally {
      setBusy(false);
    }
  }

  async function deleteAccount(account: Account) {
    if (!(await confirm({
      title: "Excluir esta conta?",
      description: `A conta ${account.name} será removida permanentemente.`,
      impact: "A exclusão só é permitida quando não há lançamentos, previsões, recorrências ou cartões vinculados à conta.",
      confirmLabel: "Excluir conta",
    }))) return;
    setBusy(true);
    try {
      await apiRequest<void>(`/api/accounts/${account.id}`, { method: "DELETE" });
      refreshAfterMutation("Conta excluída.");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Falha ao excluir a conta." });
    } finally {
      setBusy(false);
    }
  }

  async function saveCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNotice(null);
    try {
      const wasEditing = categoryEditingId !== null;
      const payload = { name: categoryName, type: categoryType };
      let savedCategory: Category;
      if (categoryEditingId) {
        savedCategory = await apiRequest<Category>(`/api/categories/${categoryEditingId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        savedCategory = await apiRequest<Category>("/api/categories", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      const returnToTransaction = returnToTransactionsAfterCategory && !wasEditing;
      setCategoryName("");
      setCategoryType("EXPENSE");
      setCategoryEditingId(null);
      setCategoryFormOpen(false);
      if (returnToTransaction) {
        setCategories((current) => [...current.filter((category) => category.id !== savedCategory.id), savedCategory]);
        setTransactionForm((current) => ({ ...current, category_id: savedCategory.id }));
        setTransactionFormOpen(true);
        setReturnToTransactionsAfterCategory(false);
        setSection("transactions");
      }
      refreshAfterMutation(wasEditing ? "Categoria atualizada." : "Categoria criada.");
    } catch (error) {
      setNotice({
        kind: "error",
        message: error instanceof Error ? error.message : "Não foi possível salvar a categoria.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function archiveCategory(category: Category) {
    if (!window.confirm(`Arquivar a categoria “${category.name}”?`)) return;
    setBusy(true);
    try {
      await apiRequest<Category>(`/api/categories/${category.id}/archive`, { method: "POST" });
      refreshAfterMutation("Categoria arquivada. Os lançamentos existentes foram preservados.");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Falha ao arquivar." });
    } finally {
      setBusy(false);
    }
  }

  async function deleteCategory(category: Category) {
    if (!(await confirm({
      title: "Excluir esta categoria?",
      description: `A categoria ${category.name} será removida permanentemente.`,
      impact: "A exclusão só é permitida quando não há lançamentos, previsões ou recorrências vinculados à categoria.",
      confirmLabel: "Excluir categoria",
    }))) return;
    setBusy(true);
    try {
      await apiRequest<void>(`/api/categories/${category.id}`, { method: "DELETE" });
      refreshAfterMutation("Categoria excluída.");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Falha ao excluir a categoria." });
    } finally {
      setBusy(false);
    }
  }

  async function saveTransaction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNotice(null);
    try {
      const payload = {
        ...transactionForm,
        amount: toDecimalString(transactionForm.amount),
        notes: transactionForm.notes || null,
      };
      if (transactionEditingId) {
        await apiRequest<Transaction>(`/api/transactions/${transactionEditingId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        await apiRequest<Transaction>("/api/transactions", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      setTransactionForm(emptyTransaction());
      setTransactionEditingId(null);
      setTransactionFormOpen(false);
      refreshAfterMutation(
        transactionEditingId ? "Lançamento atualizado." : "Lançamento registrado.",
      );
    } catch (error) {
      setNotice({
        kind: "error",
        message: error instanceof Error ? error.message : "Não foi possível salvar o lançamento.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function saveTransfer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNotice(null);
    try {
      await apiRequest<Transaction>("/api/transfers", {
        method: "POST",
        body: JSON.stringify({
          ...transferForm,
          amount: toDecimalString(transferForm.amount),
          notes: transferForm.notes || null,
        }),
      });
      setTransferForm(emptyTransfer());
      setTransferFormOpen(false);
      refreshAfterMutation("Transferência registrada. Ela não altera receitas nem despesas.");
    } catch (error) {
      setNotice({
        kind: "error",
        message: error instanceof Error ? error.message : "Não foi possível registrar a transferência.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function deleteTransaction(transaction: Transaction) {
    if (!(await confirm({
      title: "Excluir este lançamento?",
      description: `${transaction.description}, no valor de ${formatCurrency(transaction.amount)}.`,
      impact: "Os saldos das contas e os valores de faturas ou previsões vinculadas serão recalculados.",
      confirmLabel: "Excluir lançamento",
    }))) return;
    setBusy(true);
    try {
      await apiRequest<void>(`/api/transactions/${transaction.id}`, { method: "DELETE" });
      refreshAfterMutation("Lançamento excluído.");
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Falha ao excluir." });
    } finally {
      setBusy(false);
    }
  }

  function applyTransactionFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value) query.set(key, value);
    }
    setAppliedFilters(query.toString());
  }

  function clearTransactionFilters() {
    setFilters(emptyFilters());
    setAppliedFilters("");
  }

  function editAccount(account: Account) {
    setAccountEditingId(account.id);
    setAccountForm({
      name: account.name,
      type: account.type,
      opening_balance: account.opening_balance ?? "",
      opening_balance_date: account.opening_balance_date ?? dateInSaoPaulo(),
    });
    setAccountFormOpen(true);
  }

  function editCategory(category: Category) {
    setCategoryEditingId(category.id);
    setCategoryName(category.name);
    setCategoryType(category.type);
    setCategoryFormOpen(true);
  }

  function addAccountForCurrentTransaction() {
    setAccountEditingId(null);
    setAccountForm(emptyAccount());
    setAccountFormOpen(true);
    setReturnToTransactionsAfterAccount(true);
    setSection("accounts");
  }

  function addCategoryForCurrentTransaction() {
    setCategoryEditingId(null);
    setCategoryName("");
    setCategoryType(transactionForm.type);
    setCategoryFormOpen(true);
    setReturnToTransactionsAfterCategory(true);
    setSection("categories");
  }

  function editTransaction(transaction: Transaction) {
    if (!isEditableTransaction(transaction) || !transaction.account_id || !transaction.category_id) {
      return;
    }
    setTransactionEditingId(transaction.id);
    setTransactionForm({
      account_id: transaction.account_id,
      category_id: transaction.category_id,
      type: transaction.type,
      description: transaction.description,
      amount: transaction.amount,
      occurred_at: transaction.occurred_at,
      notes: transaction.notes ?? "",
    });
    setTransactionFormOpen(true);
  }

  const activeAccounts = accounts.filter((account) => account.is_active);
  const activeCategories = categories.filter((category) => !category.is_archived);
  const accountPagination = usePagination(accounts, String(accounts.length));
  const incomeCategories = categories.filter((category) => category.type === "INCOME");
  const expenseCategories = categories.filter((category) => category.type === "EXPENSE");
  const incomeCategoryPagination = usePagination(incomeCategories, String(incomeCategories.length));
  const expenseCategoryPagination = usePagination(expenseCategories, String(expenseCategories.length));
  const categoryGroups = [
    { type: "INCOME" as const, label: "Receitas", pagination: incomeCategoryPagination },
    { type: "EXPENSE" as const, label: "Despesas", pagination: expenseCategoryPagination },
  ].filter((group) => group.pagination.total > 0);
  const transactionPagination = usePagination(transactions, `${appliedFilters}:${month}`);
  const overviewCategoryPagination = usePagination(dashboard?.expenses_by_category ?? [], month);
  const overviewCardPagination = usePagination(dashboard?.cards ?? [], month);
  const forecastExpenses = dashboard?.forecast_items.filter((item) => item.type === "EXPENSE") ?? [];
  const forecastPagination = usePagination(forecastExpenses, dashboard?.forecast_end ?? month);
  const activeCategoryFilter = categories.find((category) => category.id === filters.category_id);
  const transactionCategories = activeCategories.filter(
    (category) => category.type === transactionForm.type,
  );
  const titleBySection: Record<Section, string> = {
    overview: "Visão geral",
    transactions: "Lançamentos",
    accounts: "Contas",
    categories: "Categorias",
    cards: "Cartões e faturas",
    recurrences: "Programados",
  };

  return (
    <div className={embedded ? "workspace-root finance-embedded" : "workspace-root"}>
      {!embedded && <aside className="finance-sidebar">
        <div className="brand-lockup finance-brand">
          <span className="brand-mark" aria-hidden="true">F</span>
          <span>finance<span className="brand-ai">ai</span></span>
        </div>
        <nav className="finance-nav" aria-label="Navegação financeira">
          {FINANCE_NAV_ITEMS.map(({ section: key, label, icon: Icon }) => (
            <button
              className={section === key ? "finance-nav-item selected" : "finance-nav-item"}
              key={key}
              onClick={() => setSection(key)}
              type="button"
            >
              <Icon aria-hidden="true" className="finance-nav-icon" size={17} strokeWidth={1.8} />{label}
            </button>
          ))}
        </nav>
      </aside>}

      <div className="finance-main">
        {!embedded && <header className="finance-topbar">
          <span className="eyebrow">Espaço pessoal</span>
          <div className="finance-user-menu">
            <span className="user-avatar" aria-hidden="true">{displayName.slice(0, 1).toUpperCase()}</span>
            <span className="finance-user-name">{displayName}</span>
            <button className="text-button" onClick={onLogout} type="button">Sair</button>
          </div>
        </header>}

        <main className="finance-content">
          <div className="workspace-heading">
            <div>
              <p className="eyebrow">SophIA</p>
              <h1>{titleBySection[section]}</h1>
              <p className="workspace-subtitle">Registre e acompanhe suas finanças com valores calculados pelo sistema.</p>
            </div>
            {section !== "overview" && section !== "cards" && section !== "recurrences" && (
              <div className="workspace-heading-actions">
              <button
                className="primary-button compact-button"
                onClick={() => {
                  setNotice(null);
                  if (section === "accounts") {
                    setAccountEditingId(null);
                    setAccountForm(emptyAccount());
                    setAccountFormOpen(true);
                  } else if (section === "categories") {
                    setCategoryEditingId(null);
                    setCategoryName("");
                    setCategoryType("EXPENSE");
                    setCategoryFormOpen(true);
                  } else if (section === "transactions") {
                    setTransactionEditingId(null);
                    setTransactionForm({
                      ...emptyTransaction(),
                      account_id: activeAccounts.length === 1 ? activeAccounts[0].id : "",
                    });
                    setTransactionFormOpen(true);
                  }
                }}
                type="button"
              >
                <Plus aria-hidden="true" className="button-icon" size={17} />
                {section === "accounts" ? "Nova conta" : section === "categories" ? "Nova categoria" : "Novo lançamento"}
              </button>
              {section === "transactions" && <button className="secondary-button compact-button" onClick={() => { setTransferForm(emptyTransfer()); setTransferFormOpen(true); }} type="button">Transferência</button>}
              </div>
            )}
          </div>

          {notice && <div className={`workspace-notice ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.message}</div>}

          {loading ? (
            <div className="finance-loading" role="status"><BrandMark className="loading-mark" size={30} />Carregando seus dados…</div>
          ) : (
            <>
              {section === "overview" && dashboard && (
                <>
                  <div className="overview-period-row">
                    <p>Resumo atualizado em {displayDate(dashboard.as_of)}</p>
                    <div className="month-picker"><span>Mês analisado</span>
                      <CalendarMonthInput aria-label="Mês analisado" onChange={setMonth} value={month} />
                    </div>
                  </div>
                  <section aria-label="Saldo e fluxo do período" className="overview-primary-grid">
                    <article className="overview-balance-card">
                      <span className="overview-primary-label">Saldo em contas correntes</span>
                      <strong>{dashboard.checking_balance === null ? "Indisponível" : formatCurrency(dashboard.checking_balance)}</strong>
                      <span className="overview-balance-note">
                        {dashboard.checking_balance !== null
                          ? "Somente contas correntes; poupança e outros tipos ficam separados"
                          : dashboard.incomplete_checking_account_count > 0
                            ? `Informe saldo inicial e data-base de ${dashboard.incomplete_checking_account_count} ${dashboard.incomplete_checking_account_count === 1 ? "conta corrente" : "contas correntes"}.`
                            : "Cadastre uma conta corrente para acompanhar este saldo."}
                      </span>
                    </article>
                    <section className="overview-flow-card" aria-label="Fluxo mensal">
                      <div className="overview-flow-heading"><div><p className="eyebrow">Fluxo mensal</p><h2>Entradas e saídas</h2></div><span className="surface-period">{displayMonth(month)}</span></div>
                      <div className="overview-flow-values">
                        <div><span>Receitas</span><strong className="flow-income">{formatCurrency(dashboard.monthly_income)}</strong></div>
                        <div><span>Despesas</span><strong className="flow-expense">{formatCurrency(dashboard.monthly_expenses)}</strong></div>
                        <div><span>Resultado</span><strong>{formatCurrency(dashboard.monthly_result)}</strong><small>Receitas menos despesas</small></div>
                      </div>
                    </section>
                  </section>

                  {dashboard.account_type_balances.some((group) => group.account_type !== "CHECKING") && <section aria-label="Saldos separados por tipo de conta" className="account-type-balance-strip">
                    {dashboard.account_type_balances.filter((group) => group.account_type !== "CHECKING").map((group) => <div className="account-type-balance-item" key={group.account_type}><span>{accountTypeLabel(group.account_type)}</span><strong>{group.balance === null ? "Pendente" : formatCurrency(group.balance)}</strong><small>Projeção: {group.projected_balance === null ? "indisponível" : formatCurrency(group.projected_balance)}</small></div>)}
                  </section>}

                  <section aria-label="Contas a pagar previstas" className="surface-card forecast-overview-card">
                    <div className="surface-heading"><div><p className="eyebrow">Previsão até {displayDate(dashboard.forecast_end)}</p><h2>A pagar</h2><p>Valores previstos não alteram o saldo real até serem registrados como pagos.</p></div><strong className="forecast-total">{formatCurrency(dashboard.forecast_payables_total)}</strong></div>
                    <div className="forecast-summary-grid">
                      <div><span>Em atraso</span><strong>{formatCurrency(dashboard.forecast_overdue_total)}</strong></div>
                      <div><span>Próximos 7 dias</span><strong>{formatCurrency(dashboard.forecast_next_7_days_total)}</strong></div>
                      <div><span>Restante do mês</span><strong>{formatCurrency(dashboard.forecast_rest_of_month_total)}</strong></div>
                      <div><span>Receitas previstas</span><strong>{formatCurrency(dashboard.forecast_income_total)}</strong></div>
                      <div><span>Saldo corrente projetado</span><strong>{projectedCheckingLabel(dashboard)}</strong></div>
                    </div>
                    {dashboard.forecast_unassigned_invoice_total !== "0.00" && <p className="forecast-unassigned-note">Faturas sem conta pagadora definida: {formatCurrency(dashboard.forecast_unassigned_invoice_total)}. Elas aparecem na lista, mas não reduzem o saldo projetado.</p>}
                    {forecastExpenses.length === 0 ? <p className="forecast-empty">Nenhuma conta ou fatura prevista até {displayDate(dashboard.forecast_end)}.</p> : <><div className="forecast-list">{forecastPagination.items.map((item) => <div className="forecast-row" key={item.id}><span><strong>{item.description}</strong><small>{displayDate(item.due_date)} · {item.status === "OVERDUE" ? "Em atraso" : item.status === "DUE_SOON" ? "Próximos 7 dias" : "Neste mês"}{item.account_name ? ` · ${item.account_name}` : ""}</small></span><b>{formatCurrency(item.amount)}</b></div>)}</div><PaginationControls end={forecastPagination.end} label="Paginação das contas previstas" onPageChange={forecastPagination.setPage} page={forecastPagination.page} pageCount={forecastPagination.pageCount} start={forecastPagination.start} total={forecastPagination.total} /></>}
                  </section>

                  <div className="overview-grid">
                    <section className="surface-card">
                      <div className="surface-heading"><div><p className="eyebrow">Distribuição</p><h2>Despesas por categoria</h2></div><span className="surface-period">{displayMonth(month)}</span></div>
                      {dashboard.expenses_by_category.length === 0 ? (
                        <EmptyState actionLabel={onOpenAssistant ? "Perguntar sobre o mês" : undefined} message="Ainda não há despesas neste período." onAction={onOpenAssistant ? () => onOpenAssistant("O que você pode me dizer sobre meus gastos neste mês?") : undefined} />
                      ) : (
                        <ul className="category-summary-list">
                          {overviewCategoryPagination.items.map((item) => (
                            <li key={item.category_id}><span className="category-dot" /><span>{item.category_name}</span><strong className="category-amount">{formatCurrency(item.amount)}</strong></li>
                          ))}
                        </ul>
                      )}
                      <PaginationControls end={overviewCategoryPagination.end} label="Paginação das despesas por categoria" onPageChange={overviewCategoryPagination.setPage} page={overviewCategoryPagination.page} pageCount={overviewCategoryPagination.pageCount} start={overviewCategoryPagination.start} total={overviewCategoryPagination.total} />
                    </section>
                    <section className="surface-card">
                      <div className="surface-heading"><div><p className="eyebrow">Movimentação</p><h2>Últimos lançamentos</h2></div><button className="link-button" onClick={() => setSection("transactions")} type="button">Ver todos ↗</button></div>
                      {dashboard.recent_transactions.length === 0 ? (
                        <EmptyState actionLabel={onOpenAssistant ? "Conversar sobre movimentações" : undefined} message="Seus lançamentos recentes aparecerão aqui." onAction={onOpenAssistant ? () => onOpenAssistant("Quero registrar ou entender uma movimentação financeira.") : undefined} />
                      ) : (
                        <div className="recent-list">
                          {dashboard.recent_transactions.slice(0, 5).map((transaction) => (
                            <div className="recent-row" key={transaction.id}>
                              <span className={`movement-icon ${transaction.type === "INCOME" ? "income" : transaction.type === "EXPENSE" || transaction.type === "CARD_PURCHASE" ? "expense" : "neutral"}`}>
                                {transaction.type === "INCOME" ? <ArrowDownLeft aria-hidden="true" size={16} /> : transaction.type === "TRANSFER" ? <ArrowLeftRight aria-hidden="true" size={16} /> : transaction.type === "CARD_PAYMENT" ? <CreditCard aria-hidden="true" size={16} /> : transaction.type === "CARD_PURCHASE" ? <ReceiptText aria-hidden="true" size={16} /> : <ArrowUpRight aria-hidden="true" size={16} />}
                              </span>
                              <div className="recent-description"><strong>{transaction.description}</strong><span className="recent-meta">{transactionContext(transaction, accounts)} · {displayDate(transaction.occurred_at)}</span></div>
                              <strong className={`recent-amount ${transaction.type === "INCOME" ? "amount-income" : transaction.type === "EXPENSE" || transaction.type === "CARD_PURCHASE" ? "amount-expense" : "amount-neutral"}`}>{financialAmountSign(transaction.type)}{formatCurrency(transaction.amount)}</strong>
                            </div>
                          ))}
                        </div>
                      )}
                    </section>
                  </div>
                  <section className="card-summary-grid" aria-label="Cartões de crédito">
                    {dashboard.cards.length === 0 ? (
                      <div className="surface-card card-summary-empty"><p className="eyebrow">Cartões</p><h2>Nenhum cartão cadastrado</h2><button className="link-button" onClick={() => setSection("cards")} type="button">Adicionar cartão ↗</button></div>
                    ) : overviewCardPagination.items.map((card) => (
                      <article className="surface-card card-summary" key={card.id}>
                        <div className="surface-heading"><div><p className="eyebrow">Cartão de crédito</p><h2>{card.name}</h2></div><span className="card-summary-mark"><CreditCard aria-hidden="true" size={18} /></span></div>
                        <div className="card-summary-values"><div><span>Em aberto</span><strong>{formatCurrency(card.used_limit)}</strong></div><div><span>Limite disponível</span><strong>{formatCurrency(card.available_limit)}</strong></div></div>
                        <p className="card-summary-due">{card.next_due_date ? `Próximo vencimento ${displayDate(card.next_due_date)}` : "Sem fatura em aberto"}</p>
                        <button className="link-button" onClick={() => setSection("cards")} type="button">Ver faturas ↗</button>
                      </article>
                    ))}
                  </section>
                  <PaginationControls end={overviewCardPagination.end} label="Paginação dos cartões do resumo" onPageChange={overviewCardPagination.setPage} page={overviewCardPagination.page} pageCount={overviewCardPagination.pageCount} start={overviewCardPagination.start} total={overviewCardPagination.total} />
                </>
              )}

              {section === "recurrences" && <RecurrenceWorkspace focusTarget={focusTarget} onFinanceChanged={loadFinance} />}

              {section === "accounts" && (
                <section className="surface-card data-card">
                  <div className="surface-heading"><div><p className="eyebrow">Patrimônio</p><h2>Central de contas</h2><p className="account-directory-copy">Contas que você autorizou a SophIA a acompanhar. Uma conta só é cadastrada quando você inicia e salva o formulário.</p></div><span className="record-count">{accounts.length} {accounts.length === 1 ? "conta" : "contas"}</span></div>
                  <div className="account-directory-summary">
                    <div><span>Saldo em contas correntes</span><strong>{dashboard?.checking_balance === null || !dashboard ? "Indisponível" : formatCurrency(dashboard.checking_balance)}</strong></div>
                    <div><span>Contas ativas</span><strong>{activeAccounts.length}</strong></div>
                    {dashboard?.account_type_balances.filter((group) => group.account_type !== "CHECKING").map((group) => <div key={group.account_type}><span>Saldo em {accountTypeLabel(group.account_type).toLocaleLowerCase("pt-BR")}</span><strong>{group.balance === null ? "Pendente" : formatCurrency(group.balance)}</strong></div>)}
                    {dashboard && dashboard.checking_balance === null && dashboard.incomplete_checking_account_count > 0 && <p>Informe o saldo inicial e a data-base das contas correntes pendentes para calcular o total.</p>}
                  </div>
                  {accountFormOpen && (
                    <form className="editor-form" onSubmit={saveAccount}>
                      <div className="editor-heading"><h3>{accountEditingId ? "Editar conta" : "Adicionar conta"}</h3><button className="text-button" onClick={() => { setAccountFormOpen(false); setReturnToTransactionsAfterAccount(false); }} type="button">Fechar</button></div>
                      <div className="form-grid">
                        <label className="field-label">Nome<input maxLength={100} onChange={(event) => setAccountForm({ ...accountForm, name: event.target.value })} required value={accountForm.name} /></label>
                        <label className="field-label">Tipo<select onChange={(event) => setAccountForm({ ...accountForm, type: event.target.value as AccountType })} value={accountForm.type}><option value="CHECKING">Conta corrente</option><option value="SAVINGS">Poupança</option><option value="CASH">Dinheiro</option><option value="OTHER">Outra</option></select></label>
                        <div className="field-label"><label htmlFor="account-opening-balance">Saldo inicial (opcional)</label><CurrencyInput id="account-opening-balance" onChange={(value) => setAccountForm({ ...accountForm, opening_balance: value })} placeholder="0,00" value={accountForm.opening_balance} /></div>
                        <div className="field-label"><label htmlFor="account-opening-balance-date">Data do saldo inicial</label><CalendarDateInput id="account-opening-balance-date" disabled={!accountForm.opening_balance.trim()} onChange={(value) => setAccountForm({ ...accountForm, opening_balance_date: value })} required={Boolean(accountForm.opening_balance.trim())} value={accountForm.opening_balance_date} /></div>
                      </div>
                      <div className="form-actions"><button className="primary-button compact-button" disabled={busy} type="submit">{busy ? "Salvando…" : "Salvar conta"}</button><span className="form-note">Deixe saldo e data em branco se ainda não souber. O saldo deste tipo ficará indisponível até preencher os dois.</span></div>
                    </form>
                  )}
                  {accounts.length === 0 ? <EmptyState actionLabel="Adicionar primeira conta" message="Cadastre uma conta para começar a acompanhar seu saldo." onAction={() => { setAccountForm(emptyAccount()); setAccountEditingId(null); setAccountFormOpen(true); }} /> : (
                    <><div className="table-wrap"><table className="data-table"><thead><tr><th>Conta</th><th>Tipo</th><th>Saldo atual</th><th>Situação</th><th aria-label="Ações" /></tr></thead><tbody>
                      {accountPagination.items.map((account) => <tr key={account.id}><td><strong className="cell-primary">{account.name}</strong><small className="cell-secondary">{account.opening_balance_date ? `Saldo inicial em ${displayDate(account.opening_balance_date)}` : "Saldo inicial não informado"}</small></td><td>{accountTypeLabel(account.type)}</td><td className="table-money">{account.balance === null ? "Pendente" : formatCurrency(account.balance)}</td><td><span className={account.is_active ? "state-pill active" : "state-pill archived"}>{account.is_active ? "Ativa" : "Arquivada"}</span></td><td className="row-actions">{account.is_active && <><button className="table-action" onClick={() => editAccount(account)} type="button">Editar</button><button className="table-action danger-action" disabled={busy} onClick={() => void archiveAccount(account)} type="button">Arquivar</button></>}<button className="table-action danger-action" disabled={busy} onClick={() => void deleteAccount(account)} type="button">Excluir</button></td></tr>)}
                    </tbody></table></div><PaginationControls end={accountPagination.end} label="Paginação das contas" onPageChange={accountPagination.setPage} page={accountPagination.page} pageCount={accountPagination.pageCount} start={accountPagination.start} total={accountPagination.total} /></>
                  )}
                </section>
              )}

              {section === "categories" && (
                <section className="surface-card data-card">
                  <div className="surface-heading"><div><p className="eyebrow">Classificação</p><h2>Suas categorias</h2></div><span className="record-count">{categories.length} {categories.length === 1 ? "categoria" : "categorias"}</span></div>
                  {categoryFormOpen && (
                    <form className="editor-form" onSubmit={saveCategory}>
                      <div className="editor-heading"><h3>{categoryEditingId ? "Editar categoria" : "Adicionar categoria"}</h3><button className="text-button" onClick={() => { setCategoryFormOpen(false); setReturnToTransactionsAfterCategory(false); }} type="button">Fechar</button></div>
                      <div className="form-grid category-form-grid">
                        <label className="field-label">Nome<input maxLength={100} onChange={(event) => setCategoryName(event.target.value)} required value={categoryName} /></label>
                        <label className="field-label">Tipo<select onChange={(event) => setCategoryType(event.target.value as MovementType)} value={categoryType}><option value="EXPENSE">Despesa</option><option value="INCOME">Receita</option></select></label>
                      </div>
                      <div className="form-actions"><button className="primary-button compact-button" disabled={busy} type="submit">{busy ? "Salvando…" : "Salvar categoria"}</button><span className="form-note">Arquivar preserva os lançamentos já registrados.</span></div>
                    </form>
                  )}
                  {categories.length === 0 ? <EmptyState actionLabel="Criar categoria" message="Crie categorias para classificar receitas e despesas." onAction={() => { setCategoryName(""); setCategoryEditingId(null); setCategoryFormOpen(true); }} /> : (
                    <div className="category-groups">
                      {categoryGroups.map((group) => (
                        <section aria-label={`Categorias de ${group.label.toLowerCase()}`} className={`category-group category-group-${group.type.toLowerCase()}`} key={group.type}>
                          <div className="category-group-heading"><h3>{group.label}</h3><span>{group.pagination.total} {group.pagination.total === 1 ? "categoria" : "categorias"}</span></div>
                          <div className="table-wrap"><table className="data-table"><thead><tr><th>Categoria</th><th>Situação</th><th aria-label="Ações" /></tr></thead><tbody>
                            {group.pagination.items.map((category) => <tr key={category.id}><td><button aria-label={`Ver lançamentos da categoria ${category.name}`} className="category-name-drilldown" onClick={() => { const params = new URLSearchParams({ category_id: category.id }); setFilters({ ...emptyFilters(), category_id: category.id }); setAppliedFilters(params.toString()); setSection("transactions"); }} type="button"><strong className="cell-primary">{category.name}</strong></button><button className="category-transactions-link" onClick={() => { const params = new URLSearchParams({ category_id: category.id }); setFilters({ ...emptyFilters(), category_id: category.id }); setAppliedFilters(params.toString()); setSection("transactions"); }} type="button">Ver lançamentos</button></td><td><span className={category.is_archived ? "state-pill archived" : "state-pill active"}>{category.is_archived ? "Arquivada" : "Ativa"}</span></td><td className="row-actions">{!category.is_archived && <><button className="table-action" onClick={() => editCategory(category)} type="button">Editar</button><button className="table-action danger-action" disabled={busy} onClick={() => void archiveCategory(category)} type="button">Arquivar</button></>}<button className="table-action danger-action" disabled={busy} onClick={() => void deleteCategory(category)} type="button">Excluir</button></td></tr>)}
                          </tbody></table></div><PaginationControls end={group.pagination.end} label={`Paginação das categorias de ${group.label.toLowerCase()}`} onPageChange={group.pagination.setPage} page={group.pagination.page} pageCount={group.pagination.pageCount} start={group.pagination.start} total={group.pagination.total} />
                        </section>
                      ))}
                    </div>
                  )}
                </section>
              )}

              {section === "transactions" && (
                <section className="surface-card data-card">
                  <div className="surface-heading"><div><p className="eyebrow">Histórico financeiro</p><h2>{activeCategoryFilter ? `Lançamentos · ${activeCategoryFilter.name}` : "Receitas, despesas e movimentos"}</h2></div><span className="record-count">{transactions.length} {transactions.length === 1 ? "lançamento" : "lançamentos"}</span></div>
                  <TransactionImport onImported={async (message) => { await loadFinance(); setNotice({ kind: "success", message }); }} />
                  {transactionFormOpen && (
                    <form className="editor-form" onSubmit={saveTransaction}>
                      <div className="editor-heading"><h3>{transactionEditingId ? "Editar lançamento" : "Adicionar lançamento"}</h3><button className="text-button" onClick={() => setTransactionFormOpen(false)} type="button">Fechar</button></div>
                      <div className="form-grid transaction-form-grid">
                        <label className="field-label">Tipo<select onChange={(event) => setTransactionForm({ ...transactionForm, type: event.target.value as MovementType, category_id: "" })} value={transactionForm.type}><option value="EXPENSE">Despesa</option><option value="INCOME">Receita</option></select></label>
                        <label className="field-label">Conta<select onChange={(event) => setTransactionForm({ ...transactionForm, account_id: event.target.value })} required value={transactionForm.account_id}><option value="">Selecione</option>{activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>
                        <div className="field-label"><label htmlFor="transaction-date">Data</label><CalendarDateInput id="transaction-date" onChange={(value) => setTransactionForm({ ...transactionForm, occurred_at: value })} required value={transactionForm.occurred_at} /></div>
                        <div className="field-label"><label htmlFor="transaction-amount">Valor</label><CurrencyInput id="transaction-amount" onChange={(value) => setTransactionForm({ ...transactionForm, amount: value })} placeholder="0,00" required value={transactionForm.amount} /></div>
                        <label className="field-label">Descrição<input maxLength={200} onChange={(event) => setTransactionForm({ ...transactionForm, description: event.target.value })} required value={transactionForm.description} /></label>
                        <label className="field-label">Categoria<select onChange={(event) => setTransactionForm({ ...transactionForm, category_id: event.target.value })} required value={transactionForm.category_id}><option value="">Selecione</option>{transactionCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
                        <label className="field-label full-width-field">Observações<textarea maxLength={2000} onChange={(event) => setTransactionForm({ ...transactionForm, notes: event.target.value })} rows={2} value={transactionForm.notes} /></label>
                      </div>
                      {activeAccounts.length === 0 && <p className="form-helper">Cadastre uma conta ativa antes de registrar este lançamento. <button className="text-button" onClick={addAccountForCurrentTransaction} type="button">Adicionar conta e voltar ao lançamento</button></p>}
                      {transactionCategories.length === 0 && <p className="form-helper">Você ainda não tem uma categoria de {transactionForm.type === "INCOME" ? "receita" : "despesa"}. <button className="text-button" onClick={addCategoryForCurrentTransaction} type="button">Criar categoria e voltar ao lançamento</button></p>}
                      <div className="form-actions"><button className="primary-button compact-button" disabled={busy || activeAccounts.length === 0 || transactionCategories.length === 0} type="submit">{busy ? "Salvando…" : "Salvar lançamento"}</button><span className="form-note">Valores são enviados como decimais exatos.</span></div>
                    </form>
                  )}
                  {transferFormOpen && (
                    <form className="editor-form" onSubmit={saveTransfer}>
                      <div className="editor-heading"><h3>Transferir entre contas</h3><button className="text-button" onClick={() => setTransferFormOpen(false)} type="button">Fechar</button></div>
                      <div className="form-grid transaction-form-grid">
                        <label className="field-label">Conta de origem<select onChange={(event) => setTransferForm({ ...transferForm, source_account_id: event.target.value, destination_account_id: transferForm.destination_account_id === event.target.value ? "" : transferForm.destination_account_id })} required value={transferForm.source_account_id}><option value="">Selecione</option>{activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>
                        <label className="field-label">Conta de destino<select onChange={(event) => setTransferForm({ ...transferForm, destination_account_id: event.target.value })} required value={transferForm.destination_account_id}><option value="">Selecione</option>{activeAccounts.filter((account) => account.id !== transferForm.source_account_id).map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>
                        <div className="field-label"><label htmlFor="transfer-amount">Valor</label><CurrencyInput id="transfer-amount" onChange={(value) => setTransferForm({ ...transferForm, amount: value })} placeholder="0,00" required value={transferForm.amount} /></div>
                        <div className="field-label"><label htmlFor="transfer-date">Data</label><CalendarDateInput id="transfer-date" onChange={(value) => setTransferForm({ ...transferForm, occurred_at: value })} required value={transferForm.occurred_at} /></div>
                        <label className="field-label full-width-field">Observações<textarea maxLength={2000} onChange={(event) => setTransferForm({ ...transferForm, notes: event.target.value })} rows={2} value={transferForm.notes} /></label>
                      </div>
                      {activeAccounts.length < 2 && <p className="form-helper">Cadastre duas contas ativas antes de registrar uma transferência.</p>}
                      <div className="form-actions"><button className="primary-button compact-button" disabled={busy || activeAccounts.length < 2} type="submit">{busy ? "Salvando…" : "Registrar transferência"}</button><span className="form-note">A transferência não gera receita ou despesa.</span></div>
                    </form>
                  )}
                  <form className="filter-form" onSubmit={applyTransactionFilters}>
                    <div className="field-label"><label htmlFor="transaction-filter-start-date">De</label><CalendarDateInput id="transaction-filter-start-date" onChange={(value) => setFilters({ ...filters, start_date: value })} value={filters.start_date} /></div>
                    <div className="field-label"><label htmlFor="transaction-filter-end-date">Até</label><CalendarDateInput id="transaction-filter-end-date" onChange={(value) => setFilters({ ...filters, end_date: value })} value={filters.end_date} /></div>
                    <label className="field-label">Conta<select onChange={(event) => setFilters({ ...filters, account_id: event.target.value })} value={filters.account_id}><option value="">Todas</option>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>
                    <label className="field-label">Categoria<select onChange={(event) => setFilters({ ...filters, category_id: event.target.value })} value={filters.category_id}><option value="">Todas</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
                    <label className="field-label">Tipo<select onChange={(event) => setFilters({ ...filters, type: event.target.value as TransactionFilters["type"] })} value={filters.type}><option value="">Todos</option><option value="INCOME">Receita</option><option value="EXPENSE">Despesa</option><option value="TRANSFER">Transferência</option><option value="CARD_PURCHASE">Compra no cartão</option><option value="CARD_PAYMENT">Pagamento de fatura</option></select></label>
                    <label className="field-label search-field">Buscar<input onChange={(event) => setFilters({ ...filters, q: event.target.value })} placeholder="Descrição, categoria…" value={filters.q} /></label>
                    <div className="filter-actions"><button className="primary-button compact-button" type="submit">Filtrar</button><button className="text-button" onClick={clearTransactionFilters} type="button">Limpar</button></div>
                  </form>
                  {transactions.length === 0 ? <EmptyState actionLabel={appliedFilters ? "Limpar filtros" : onOpenAssistant ? "Conversar com o assistente" : undefined} message={appliedFilters ? "Nenhum lançamento corresponde aos filtros." : "Ainda não há lançamentos neste período."} onAction={appliedFilters ? clearTransactionFilters : onOpenAssistant ? () => onOpenAssistant("Quero registrar um lançamento financeiro.") : undefined} /> : (
                    <><div className="table-wrap"><table className="data-table transaction-table"><thead><tr><th>Lançamento</th><th>Categoria / origem / destino</th><th>Data</th><th>Tipo</th><th>Valor</th><th aria-label="Ações" /></tr></thead><tbody>
                      {transactionPagination.items.map((transaction) => {
                        const tone = transaction.type === "INCOME" ? "income" : transaction.type === "EXPENSE" || transaction.type === "CARD_PURCHASE" ? "expense" : "neutral";
                        return <tr key={transaction.id}><td><strong className="cell-primary">{transaction.description}</strong>{transaction.notes && <small className="cell-secondary">{transaction.notes}</small>}</td><td>{transactionContext(transaction, accounts)}</td><td>{displayDate(transaction.occurred_at)}</td><td><span className={`type-text ${tone}`}>{financialTransactionLabel(transaction.type)}</span></td><td className="table-money">{financialAmountSign(transaction.type)}{formatCurrency(transaction.amount)}</td><td className="row-actions">{isEditableTransaction(transaction) && <button className="table-action" onClick={() => editTransaction(transaction)} type="button">Editar</button>}<button className="table-action danger-action" disabled={busy} onClick={() => void deleteTransaction(transaction)} type="button">Excluir</button></td></tr>;
                      })}
                    </tbody></table></div><PaginationControls end={transactionPagination.end} label="Paginação dos lançamentos" onPageChange={transactionPagination.setPage} page={transactionPagination.page} pageCount={transactionPagination.pageCount} start={transactionPagination.start} total={transactionPagination.total} /></>
                  )}
                </section>
              )}

              {section === "cards" && (
                <CreditCardWorkspace
                  accounts={accounts}
                  categories={categories}
                  focusTarget={focusTarget?.source === "CARD_INVOICE" ? focusTarget : null}
                  onFinanceChanged={loadFinance}
                />
              )}
            </>
          )}
          <footer className="finance-footer"><span>SophIA</span><span>BRL · America/Sao_Paulo · dados privados</span></footer>
          {confirmationDialog}
        </main>
      </div>
    </div>
  );
}

function EmptyState({ message, actionLabel, onAction }: { message: string; actionLabel?: string; onAction?: () => void }) {
  return <div className="empty-state"><span className="empty-mark" aria-hidden="true">↗</span><p>{message}</p>{actionLabel && onAction && <button className="empty-state-action" onClick={onAction} type="button">{actionLabel}<span aria-hidden="true">↗</span></button>}</div>;
}
