"use client";

import { useCallback, useEffect, useRef, useState, type ChangeEvent, type ClipboardEvent, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type TouchEvent as ReactTouchEvent, type UIEvent as ReactUIEvent } from "react";
import Image from "next/image";
import {
  Archive,
  ArrowDownLeft,
  ArrowLeftRight,
  ArrowUp,
  ArrowUpRight,
  Bell,
  BellRing,
  ChartNoAxesCombined,
  CreditCard,
  TriangleAlert,
  ImagePlus,
  Landmark,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Menu,
  MessageSquare,
  MoreHorizontal,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Pencil,
  ReceiptText,
  RefreshCw,
  Repeat2,
  SlidersHorizontal,
  Square,
  Sun,
  Tags,
  WalletCards,
  X,
  type LucideIcon,
} from "lucide-react";

import { FinanceWorkspace } from "@/components/finance-workspace";
import { FirstUseSetup } from "@/components/first-use-setup";
import { BrandMark } from "@/components/brand-mark";
import { ApiError, apiRequest } from "@/lib/api";
import { useEditorScroll } from "@/lib/use-editor-scroll";
import type { FinanceFocusTarget } from "@/lib/finance-types";
import { formatCurrency } from "@/lib/money";
import { PaginationControls, usePagination } from "@/components/pagination";

type FinanceSection = "overview" | "transactions" | "accounts" | "categories" | "cards" | "recurrences";
type WorkspaceView = "chat" | "finance" | "settings" | "account";
type Theme = "light" | "dark";
type WorkspaceRefreshSnapshot = {
  version: 1;
  view: WorkspaceView;
  financeSection: FinanceSection;
  conversationId: string | null;
};

const WORKSPACE_REFRESH_SNAPSHOT_KEY = "sophia-workspace-refresh-v1";
const CONVERSATION_HISTORY_BATCH_SIZE = 10;

function readWorkspaceRefreshSnapshot(): WorkspaceRefreshSnapshot | null {
  try {
    const stored = window.sessionStorage.getItem(WORKSPACE_REFRESH_SNAPSHOT_KEY);
    window.sessionStorage.removeItem(WORKSPACE_REFRESH_SNAPSHOT_KEY);
    if (!stored) return null;
    const value: unknown = JSON.parse(stored);
    if (!value || typeof value !== "object") return null;
    const snapshot = value as Partial<WorkspaceRefreshSnapshot>;
    const views: WorkspaceView[] = ["chat", "finance", "settings", "account"];
    const sections: FinanceSection[] = ["overview", "transactions", "accounts", "categories", "cards", "recurrences"];
    if (snapshot.version !== 1 || !views.includes(snapshot.view as WorkspaceView) || !sections.includes(snapshot.financeSection as FinanceSection)) return null;
    return {
      version: 1,
      view: snapshot.view as WorkspaceView,
      financeSection: snapshot.financeSection as FinanceSection,
      conversationId: typeof snapshot.conversationId === "string" ? snapshot.conversationId : null,
    };
  } catch {
    return null;
  }
}

function workspaceRouteFromLocation(): { view: WorkspaceView; section: FinanceSection } | null {
  const params = new URLSearchParams(window.location.search);
  const view = params.get("view");
  const section = params.get("section");
  const views: WorkspaceView[] = ["chat", "finance", "settings", "account"];
  const sections: FinanceSection[] = ["overview", "transactions", "accounts", "categories", "cards", "recurrences"];
  if (!view && !section) return { view: "chat", section: "overview" };
  if (view && !views.includes(view as WorkspaceView)) return null;
  if (section && !sections.includes(section as FinanceSection)) return null;
  return {
    view: section ? "finance" : (view as WorkspaceView | null) ?? "chat",
    section: (section as FinanceSection | null) ?? "overview",
  };
}

type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

type StructuredItem = {
  type: string;
  data?: unknown;
  snapshot_kind?: string;
  tool_call_id?: string;
  status?: string;
};

type AssistantMessage = {
  id: string;
  role: "USER" | "ASSISTANT";
  content: string;
  structured_content?: StructuredItem[] | null;
  imagePreviews?: { id: string; dataUrl: string }[];
  pending?: boolean;
  interrupted?: boolean;
};

type ChatImageAttachment = { id: string; dataUrl: string };

let optimisticMessageSequence = 0;

function createOptimisticMessageId() {
  optimisticMessageSequence += 1;
  return `optimistic-${Date.now()}-${optimisticMessageSequence}`;
}

async function chatRequestIdempotencyKey(conversationId: string, requestBody: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(requestBody));
  const fingerprint = Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  const storageKey = `sophia:chat-idempotency:${conversationId}:${fingerprint}`;
  const key = window.sessionStorage.getItem(storageKey) ?? crypto.randomUUID();
  window.sessionStorage.setItem(storageKey, key);
  return { key, storageKey };
}

type AIStatus = {
  configured: boolean;
  provider: "ollama" | "chatgpt_plan";
  fast_model: string;
  smart_model: string;
  diagnostics_enabled: boolean;
};

type AIDiagnostic = {
  id: string;
  created_at: string;
  conversation_id: string;
  model: string | null;
  tool_name: string | null;
  status: string;
  duration_ms: number | null;
  preparation_ms: number | null;
  first_output_ms: number | null;
  first_text_ms: number | null;
  available_tool_count: number | null;
  input_tokens: number | null;
  cached_input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost_usd: string | null;
  error_summary: string | null;
};

type Usage = {
  calls_today: number;
  input_tokens_today: number;
  output_tokens_today: number;
  cost_usd_today: string | null;
  calls_month: number;
  input_tokens_month: number;
  output_tokens_month: number;
  cost_usd_month: string | null;
};

type Memory = { id: string; content: string; created_at: string };
type ManagedUser = { id: string; email: string; display_name: string; created_at: string; mfa_enrolled: boolean };
type AssistantPreferences = {
  responseStyle: "concise" | "balanced" | "detailed";
  defaultAccount: string;
  mainCard: string;
  ambiguityBehavior: "ask" | "use_context";
  proactivity: "on_request" | "relevant";
};

const ASSISTANT_PREFERENCES_PREFIX = "Preferências explícitas do Meu Assistente: ";
const DEFAULT_ASSISTANT_PREFERENCES: AssistantPreferences = {
  responseStyle: "balanced",
  defaultAccount: "",
  mainCard: "",
  ambiguityBehavior: "ask",
  proactivity: "on_request",
};

type Dashboard = {
  as_of: string;
  period_start: string;
  period_end: string;
  checking_balance: string | null;
  incomplete_checking_account_count: number;
  account_type_balances: { account_type: "CHECKING" | "SAVINGS" | "CASH" | "OTHER"; balance: string | null; projected_balance: string | null; account_count: number; incomplete_account_count: number }[];
  monthly_income: string;
  monthly_expenses: string;
  monthly_result: string;
  expenses_by_category: { category_id: string; category_name: string; amount: string }[];
  cards: {
    id: string;
    name: string;
    used_limit: string;
    available_limit: string;
    next_due_date: string | null;
  }[];
  recent_transactions: {
    id: string;
    type: "INCOME" | "EXPENSE" | "TRANSFER" | "CARD_PURCHASE" | "CARD_PAYMENT";
    description: string;
    amount: string;
    occurred_at: string;
    category_name: string | null;
    account_id?: string | null;
    source_account_id?: string | null;
    destination_account_id?: string | null;
  }[];
  forecast_start: string;
  forecast_end: string;
  forecast_payables_total: string;
  forecast_overdue_total: string;
  forecast_next_7_days_total: string;
  forecast_rest_of_month_total: string;
  forecast_income_total: string;
  forecast_unassigned_invoice_total: string;
  forecast_items: { id: string; source: "RECURRENCE" | "COMMITMENT" | "CARD_INVOICE"; credit_card_id: string | null; description: string; type: "INCOME" | "EXPENSE"; due_date: string; amount: string; account_type: "CHECKING" | "SAVINGS" | "CASH" | "OTHER" | null; account_name: string | null; card_name: string | null; status: "OVERDUE" | "DUE_SOON" | "PLANNED" }[];
};

type ContextAccount = { id: string; name: string; type: "CHECKING" | "SAVINGS" | "CASH" | "OTHER"; balance: string | null; is_active: boolean };
type ContextCard = {
  id: string;
  name: string;
  is_active: boolean;
  institution: string | null;
  credit_limit: string;
  used_limit: string;
  available_limit: string;
  closing_day: number;
  due_day: number;
  next_due_date: string | null;
};
type ContextInvoice = {
  id: string;
  credit_card_name: string;
  closing_date: string;
  due_date: string;
  total: string;
  outstanding: string;
  status: string;
};

type PendingAction = { id: string; action: "confirm" | "cancel" } | null;

const NAV_ITEMS: { view: WorkspaceView; section?: FinanceSection; label: string; icon: LucideIcon }[] = [
  { view: "finance", section: "overview", label: "Visão geral", icon: LayoutDashboard },
  { view: "finance", section: "transactions", label: "Lançamentos", icon: ReceiptText },
  { view: "finance", section: "accounts", label: "Contas", icon: Landmark },
  { view: "finance", section: "cards", label: "Cartões", icon: CreditCard },
  { view: "finance", section: "recurrences", label: "Programados", icon: Repeat2 },
  { view: "finance", section: "categories", label: "Categorias", icon: Tags },
  { view: "settings", label: "Preferências", icon: SlidersHorizontal },
];

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function hasMoneyValue(value: string | null): value is string {
  return value !== null && !/^[+-]?0+(?:\.0+)?$/.test(value);
}

function renderAssistantText(value: string) {
  const parts: ReactNode[] = [];
  const emphasis = /\*\*([^*\n]+)\*\*/g;
  let cursor = 0;

  for (const match of value.matchAll(emphasis)) {
    const start = match.index ?? 0;
    if (start > cursor) parts.push(value.slice(cursor, start));
    parts.push(<strong key={`${start}-${match[1]}`}>{match[1]}</strong>);
    cursor = start + match[0].length;
  }

  if (cursor < value.length) parts.push(value.slice(cursor));
  return parts;
}

function displayDate(value: string): string {
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "short",
    timeZone: "America/Sao_Paulo",
  }).format(parsed);
}

function daysBetweenDates(from: string, to: string): number {
  const fromDay = Date.parse(`${from.slice(0, 10)}T00:00:00Z`);
  const toDay = Date.parse(`${to.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(fromDay) || Number.isNaN(toDay)) return 0;
  return Math.round((toDay - fromDay) / 86_400_000);
}

function dueDateLabel(item: Dashboard["forecast_items"][number], today: string): string {
  const days = daysBetweenDates(today, item.due_date);
  if (days < 0) return `Atrasado há ${Math.abs(days)} ${Math.abs(days) === 1 ? "dia" : "dias"}`;
  if (days === 0) return "Vence hoje";
  if (days === 1) return "Vence amanhã";
  return `Vence em ${days} dias`;
}

function DueNotifications({
  dashboard,
  openForecast,
  refreshDashboard,
}: {
  dashboard: Dashboard | null;
  openForecast: (item?: Dashboard["forecast_items"][number]) => void;
  refreshDashboard: () => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const alertItems = dashboard?.forecast_items.filter((item) =>
    item.type === "EXPENSE" && (item.status === "OVERDUE" || item.status === "DUE_SOON"),
  ) ?? [];
  const overdueItems = alertItems.filter((item) => item.status === "OVERDUE");
  const upcomingItems = alertItems.filter((item) => item.status === "DUE_SOON");
  const overduePagination = usePagination(overdueItems, String(overdueItems.length));
  const upcomingPagination = usePagination(upcomingItems, String(upcomingItems.length));
  const overdueCount = overdueItems.length;
  const laterCount = dashboard?.forecast_items.filter((item) =>
    item.type === "EXPENSE" && item.status === "PLANNED",
  ).length ?? 0;

  useEffect(() => {
    if (!open) return;
    function closeOnOutsideClick(event: PointerEvent) {
      if (event.target instanceof Node && !containerRef.current?.contains(event.target)) setOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const BellIcon = alertItems.length > 0 ? BellRing : Bell;
  const renderItems = (items: Dashboard["forecast_items"]) => items.map((item) => {
    const overdue = item.status === "OVERDUE";
    return (
      <button className={`notification-item${overdue ? " urgent" : ""}`} key={item.id} onClick={() => { setOpen(false); openForecast(item); }} type="button">
        <span className={`notification-icon${overdue ? " urgent" : ""}`} aria-hidden="true">
          {overdue ? <TriangleAlert size={17} /> : <Bell size={16} />}
        </span>
        <span className="notification-copy">
          <strong>{item.description}</strong>
          <small>{dueDateLabel(item, dashboard?.as_of ?? "")} · {displayDate(item.due_date)}{item.account_name ? ` · ${item.account_name}` : item.card_name ? ` · ${item.card_name}` : ""}</small>
        </span>
        <b className="notification-amount">{formatCurrency(item.amount)}</b>
      </button>
    );
  });

  return (
    <div className="assistant-notifications" ref={containerRef}>
      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={alertItems.length ? `Avisos: ${alertItems.length} vencimento(s) próximo(s) ou em atraso` : "Abrir avisos"}
        className="assistant-notifications-toggle"
        onClick={() => {
          setOpen((current) => !current);
          if (!open) refreshDashboard();
        }}
        title="Avisos de vencimentos"
        type="button"
      >
        <BellIcon aria-hidden="true" size={17} strokeWidth={1.9} />
        <span>Avisos</span>
        {alertItems.length > 0 && <b className={overdueCount ? "notification-count urgent" : "notification-count"}>{alertItems.length > 9 ? "9+" : alertItems.length}</b>}
      </button>
      {open && (
        <section aria-label="Avisos de vencimentos" className="assistant-notifications-panel" role="dialog">
          <header className="notifications-heading">
            <div>
              <p className="eyebrow">Acompanhe seus compromissos</p>
              <h2>Avisos</h2>
            </div>
            <span className={overdueCount ? "notifications-summary urgent" : "notifications-summary"}>
              {alertItems.length ? `${alertItems.length} ${alertItems.length === 1 ? "aviso" : "avisos"}` : "Tudo em dia"}
            </span>
          </header>
          {!dashboard ? (
            <p className="notifications-empty">Carregando seus vencimentos…</p>
          ) : alertItems.length ? (
            <>
              {overdueItems.length > 0 && <><p className="notifications-group-label urgent">Em atraso</p><div className="notifications-list">{renderItems(overduePagination.items)}</div><PaginationControls end={overduePagination.end} label="Paginação dos avisos em atraso" onPageChange={overduePagination.setPage} page={overduePagination.page} pageCount={overduePagination.pageCount} start={overduePagination.start} total={overduePagination.total} /></>}
              {upcomingItems.length > 0 && <><p className="notifications-group-label">Vencem nos próximos 7 dias</p><div className="notifications-list">{renderItems(upcomingPagination.items)}</div><PaginationControls end={upcomingPagination.end} label="Paginação dos próximos avisos" onPageChange={upcomingPagination.setPage} page={upcomingPagination.page} pageCount={upcomingPagination.pageCount} start={upcomingPagination.start} total={upcomingPagination.total} /></>}
              {laterCount > 0 && <p className="notifications-later">Mais {laterCount} {laterCount === 1 ? "pagamento previsto" : "pagamentos previstos"} para depois dos próximos 7 dias.</p>}
            </>
          ) : (
            <p className="notifications-empty">Você não tem pagamentos atrasados ou vencendo nos próximos 7 dias.</p>
          )}
          <footer className="notifications-footer">
            <span>Atualizado em {dashboard ? displayDate(dashboard.as_of) : "—"}</span>
            <button onClick={() => openForecast()} type="button">Ver previsão completa</button>
          </footer>
        </section>
      )}
    </div>
  );
}

function displayMonth(value: string): string {
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return "Este mês";
  return new Intl.DateTimeFormat("pt-BR", {
    month: "long",
    year: "numeric",
    timeZone: "America/Sao_Paulo",
  }).format(parsed);
}

function accountTypeLabel(value: ContextAccount["type"]): string {
  return { CHECKING: "Conta corrente", SAVINGS: "Poupança", CASH: "Dinheiro", OTHER: "Outras contas" }[value];
}

function previousMonthQuery(periodStart: string): string | null {
  const match = /^(\d{4})-(\d{2})-/.exec(periodStart);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (month < 1 || month > 12) return null;
  const previousYear = month === 1 ? year - 1 : year;
  const previousMonth = month === 1 ? 12 : month - 1;
  return `year=${previousYear}&month=${previousMonth}`;
}

function displayTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Data indisponível";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "America/Sao_Paulo",
  }).format(parsed);
}

function diagnosticStatusLabel(value: string): string {
  if (value === "SUCCEEDED") return "Concluído";
  if (value === "FAILED") return "Falhou";
  if (value === "PENDING_CONFIRMATION") return "Aguardando confirmação";
  if (value === "CANCELLED") return "Cancelado";
  return value;
}

function formatUsdCost(value: string | null | undefined): string {
  if (!value) return "—";
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) return "—";
  const [, sign, whole, fraction = ""] = match;
  const groupedWhole = new Intl.NumberFormat("en-US").format(BigInt(whole));
  return `${sign}$${groupedWhole}.${fraction.padEnd(8, "0")}`;
}

function currentGreeting(): string {
  const hourText = new Intl.DateTimeFormat("pt-BR", {
    hour: "numeric",
    hourCycle: "h23",
    timeZone: "America/Sao_Paulo",
  }).format(new Date());
  const hour = Number(hourText);
  return hour < 12 ? "Bom dia" : hour < 18 ? "Boa tarde" : "Boa noite";
}

function activeNav(view: WorkspaceView, section: FinanceSection): string {
  if (view === "finance") return `finance-${section}`;
  return view;
}

function parseAssistantPreferences(content: string | undefined): AssistantPreferences {
  if (!content?.startsWith(ASSISTANT_PREFERENCES_PREFIX)) return DEFAULT_ASSISTANT_PREFERENCES;
  try {
    const value = record(JSON.parse(content.slice(ASSISTANT_PREFERENCES_PREFIX.length)));
    const responseStyle = stringValue(value?.responseStyle);
    const ambiguityBehavior = stringValue(value?.ambiguityBehavior);
    const proactivity = stringValue(value?.proactivity);
    return {
      responseStyle: responseStyle === "concise" || responseStyle === "detailed" ? responseStyle : "balanced",
      defaultAccount: stringValue(value?.defaultAccount) ?? "",
      mainCard: stringValue(value?.mainCard) ?? "",
      ambiguityBehavior: ambiguityBehavior === "use_context" ? "use_context" : "ask",
      proactivity: proactivity === "relevant" ? "relevant" : "on_request",
    };
  } catch {
    return DEFAULT_ASSISTANT_PREFERENCES;
  }
}

export function AssistantWorkspace({
  avatarUrl,
  displayName,
  email,
  mfaRequired,
  mfaEnrolled,
  onAvatarUrlChange,
  onDisplayNameChange,
  onLogout,
  theme,
  onThemeChange,
}: {
  avatarUrl: string | null;
  displayName: string;
  email: string;
  mfaRequired: boolean;
  mfaEnrolled: boolean;
  onAvatarUrlChange: (avatarUrl: string | null) => void;
  onDisplayNameChange: (displayName: string) => void;
  onLogout: () => void;
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
}) {
  const [view, setView] = useState<WorkspaceView>("chat");
  const [financeSection, setFinanceSection] = useState<FinanceSection>("overview");
  const financeSectionRef = useRef<FinanceSection>(financeSection);
  const navigateTo = useCallback((
    nextView: WorkspaceView,
    nextSection?: FinanceSection,
    replace = false,
  ) => {
    const targetSection = nextSection ?? financeSectionRef.current;
    setView(nextView);
    setFinanceSection(targetSection);
    financeSectionRef.current = targetSection;
    const url = new URL(window.location.href);
    url.searchParams.set("view", nextView);
    if (nextView === "finance") url.searchParams.set("section", targetSection);
    else url.searchParams.delete("section");
    if (replace) window.history.replaceState(null, "", url);
    else {
      const currentRoute = workspaceRouteFromLocation();
      const sameRoute = currentRoute?.view === nextView &&
        (nextView !== "finance" || currentRoute.section === targetSection);
      if (!sameRoute) window.history.pushState(null, "", url);
    }
  }, []);
  const [financeFocusTarget, setFinanceFocusTarget] = useState<FinanceFocusTarget | null>(null);
  const financeFocusRequestId = useRef(0);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [visibleConversationCount, setVisibleConversationCount] = useState(CONVERSATION_HISTORY_BATCH_SIZE);
  const lastHistoryAutoLoadHeightRef = useRef(0);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [contextAccounts, setContextAccounts] = useState<ContextAccount[]>([]);
  const [contextCards, setContextCards] = useState<ContextCard[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [diagnostics, setDiagnostics] = useState<AIDiagnostic[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [draft, setDraft] = useState("");
  const [attachedImages, setAttachedImages] = useState<ChatImageAttachment[]>([]);
  const [attachedImageError, setAttachedImageError] = useState("");
  const [greeting, setGreeting] = useState("Olá");
  const [loading, setLoading] = useState(true);
  const [firstUseRequired, setFirstUseRequired] = useState<boolean | null>(null);
  const [sending, setSending] = useState(false);
  const [responseProgress, setResponseProgress] = useState("");
  const [loadingSettings, setLoadingSettings] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [activeTool, setActiveTool] = useState("");
  const [error, setError] = useState("");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [contextPanelOpen, setContextPanelOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [refreshingApp, setRefreshingApp] = useState(false);
  const [conversationMenuId, setConversationMenuId] = useState<string | null>(null);
  const [editingConversationId, setEditingConversationId] = useState<string | null>(null);
  const [conversationTitleDraft, setConversationTitleDraft] = useState("");
  const [busyConversationId, setBusyConversationId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const layoutNodeRef = useRef<HTMLDivElement | null>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const menuToggleRef = useRef<HTMLButtonElement>(null);
  const sidebarTouchStartRef = useRef<{ x: number; y: number; insideSidebar: boolean } | null>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const attachmentInputRef = useRef<HTMLInputElement>(null);
  const conversationRenameRef = useRef<HTMLInputElement>(null);
  const activeRequestControllerRef = useRef<AbortController | null>(null);
  const refreshSnapshotRef = useRef<WorkspaceRefreshSnapshot | null | undefined>(undefined);

  const preventNativeBackGesture = useCallback((event: TouchEvent) => {
    if (!window.matchMedia("(max-width: 760px)").matches || event.touches.length !== 1) return;
    if (event.touches[0]?.clientX <= 24) event.preventDefault();
  }, []);
  const layoutRef = useCallback((layout: HTMLDivElement | null) => {
    layoutNodeRef.current?.removeEventListener("touchstart", preventNativeBackGesture, true);
    layoutNodeRef.current = layout;
    // Safari treats a left-edge swipe as browser Back unless the app claims touchstart.
    layout?.addEventListener("touchstart", preventNativeBackGesture, { capture: true, passive: false });
  }, [preventNativeBackGesture]);

  const loadMoreConversationsOnScroll = useCallback((event: ReactUIEvent<HTMLDivElement>) => {
    const history = event.currentTarget;
    const nearEnd = history.scrollHeight - history.scrollTop - history.clientHeight <= 48;
    if (!nearEnd || lastHistoryAutoLoadHeightRef.current === history.scrollHeight || visibleConversationCount >= conversations.length) return;
    lastHistoryAutoLoadHeightRef.current = history.scrollHeight;
    setVisibleConversationCount((count) => Math.min(count + CONVERSATION_HISTORY_BATCH_SIZE, conversations.length));
  }, [conversations.length, visibleConversationCount]);

  useEffect(() => {
    if (view !== "chat" || !conversationId) return;
    const index = conversations.findIndex((conversation) => conversation.id === conversationId);
    if (index >= visibleConversationCount) {
      const requiredCount = Math.ceil((index + 1) / CONVERSATION_HISTORY_BATCH_SIZE) * CONVERSATION_HISTORY_BATCH_SIZE;
      setVisibleConversationCount((count) => Math.max(count, requiredCount));
    }
  }, [conversationId, conversations, view, visibleConversationCount]);

  useEffect(() => {
    if (!mobileMenuOpen || window.matchMedia("(min-width: 761px)").matches) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = sidebarRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    const first = focusable?.[0];
    const last = focusable?.[focusable.length - 1];
    first?.focus();

    function handleDrawerKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobileMenuOpen(false);
        return;
      }
      if (event.key !== "Tab" || !first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleDrawerKeyDown);
    return () => {
      document.removeEventListener("keydown", handleDrawerKeyDown);
      document.body.style.overflow = previousOverflow;
      requestAnimationFrame(() => menuToggleRef.current?.focus());
    };
  }, [mobileMenuOpen]);

  function handleSidebarTouchStart(event: ReactTouchEvent<HTMLDivElement>) {
    if (!window.matchMedia("(max-width: 760px)").matches || event.touches.length !== 1) {
      sidebarTouchStartRef.current = null;
      return;
    }
    const touch = event.touches[0];
    const target = event.target;
    const insideSidebar = target instanceof Element && target.closest(".assistant-sidebar") !== null;
    sidebarTouchStartRef.current = (!mobileMenuOpen && touch.clientX <= 24) || (mobileMenuOpen && insideSidebar)
      ? { x: touch.clientX, y: touch.clientY, insideSidebar }
      : null;
  }

  function handleSidebarTouchEnd(event: ReactTouchEvent<HTMLDivElement>) {
    const start = sidebarTouchStartRef.current;
    sidebarTouchStartRef.current = null;
    if (!start || !window.matchMedia("(max-width: 760px)").matches) return;
    const touch = event.changedTouches[0];
    if (!touch) return;
    const deltaX = touch.clientX - start.x;
    const deltaY = touch.clientY - start.y;
    if (Math.abs(deltaX) < 52 || Math.abs(deltaX) < Math.abs(deltaY) * 1.25) return;
    if (deltaX > 0 && !mobileMenuOpen && start.x <= 24) setMobileMenuOpen(true);
    if (deltaX < 0 && mobileMenuOpen && start.insideSidebar) setMobileMenuOpen(false);
  }

  const loadConversations = useCallback(async () => {
    const rows = await apiRequest<Conversation[]>("/api/ai/conversations");
    setConversations(rows);
    return rows;
  }, []);

  const loadConversation = useCallback(async (id: string) => {
    const detail = await apiRequest<Conversation & { messages: AssistantMessage[] }>(
      `/api/ai/conversations/${id}`,
    );
    setConversationId(detail.id);
    setMessages(detail.messages);
  }, []);

  const loadDashboard = useCallback(async () => {
    const [summaryResult, accountsResult, cardsResult] = await Promise.allSettled([
      apiRequest<Dashboard>("/api/dashboard/summary"),
      apiRequest<ContextAccount[]>("/api/accounts"),
      apiRequest<ContextCard[]>("/api/cards"),
    ]);
    setDashboard(summaryResult.status === "fulfilled" ? summaryResult.value : null);
    setContextAccounts(accountsResult.status === "fulfilled" ? accountsResult.value : []);
    setContextCards(cardsResult.status === "fulfilled" ? cardsResult.value : []);
  }, []);

  const loadSettings = useCallback(async () => {
    setLoadingSettings(true);
    setError("");
    try {
      const [newStatus, newUsage, newMemories] = await Promise.all([
        apiRequest<AIStatus>("/api/ai/status"),
        apiRequest<Usage>("/api/ai/usage"),
        apiRequest<Memory[]>("/api/ai/memories"),
      ]);
      const newDiagnostics = newStatus.diagnostics_enabled
        ? await apiRequest<AIDiagnostic[]>("/api/ai/diagnostics")
        : [];
      setStatus(newStatus);
      setUsage(newUsage);
      setMemories(newMemories);
      setDiagnostics(newDiagnostics);
    } catch (settingsError) {
      setError(settingsError instanceof Error ? settingsError.message : "Não foi possível carregar as preferências.");
    } finally {
      setLoadingSettings(false);
    }
  }, []);

  useEffect(() => {
    const applyLocation = () => {
      const route = workspaceRouteFromLocation();
      if (!route) return;
      setView(route.view);
      setFinanceSection(route.section);
      financeSectionRef.current = route.section;
      setFinanceFocusTarget(null);
      setMobileMenuOpen(false);
      if (route.view === "settings") void loadSettings();
    };
    applyLocation();
    window.addEventListener("popstate", applyLocation);
    return () => window.removeEventListener("popstate", applyLocation);
  }, [loadSettings]);

  useEffect(() => {
    setGreeting(currentGreeting());
    let mounted = true;
    async function loadInitialData() {
      if (refreshSnapshotRef.current === undefined) {
        refreshSnapshotRef.current = readWorkspaceRefreshSnapshot();
      }
      const refreshSnapshot = refreshSnapshotRef.current;
      try {
        const [aiStatus, rows, existingAccounts] = await Promise.all([
          apiRequest<AIStatus>("/api/ai/status"),
          apiRequest<Conversation[]>("/api/ai/conversations"),
          apiRequest<ContextAccount[]>("/api/accounts?include_archived=true"),
        ]);
        if (!mounted) return;
        setStatus(aiStatus);
        setConversations(rows);
        setFirstUseRequired(existingAccounts.length === 0);
        if (refreshSnapshot) {
          navigateTo(refreshSnapshot.view, refreshSnapshot.financeSection, true);
          if (refreshSnapshot.view === "chat" && refreshSnapshot.conversationId && rows.some((row) => row.id === refreshSnapshot.conversationId)) {
            try {
              await loadConversation(refreshSnapshot.conversationId);
            } catch (conversationError) {
              setError(conversationError instanceof Error ? conversationError.message : "Não foi possível restaurar a conversa.");
            }
          } else if (refreshSnapshot.view === "settings") {
            void loadSettings();
          }
        }
        // A sessão começa na home conversacional; o histórico permanece acessível na sidebar.
      } catch (loadError) {
        if (mounted) {
          setFirstUseRequired(false);
          setError(loadError instanceof Error ? loadError.message : "Não foi possível carregar o assistente.");
        }
      } finally {
        if (mounted) setLoading(false);
      }
    }
    void loadInitialData();
    void loadDashboard();
    return () => {
      mounted = false;
    };
  }, [loadConversation, loadDashboard, loadSettings, navigateTo]);

  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void loadDashboard();
    };
    const interval = window.setInterval(refreshWhenVisible, 5 * 60 * 1000);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [loadDashboard]);

  function completeFirstUse() {
    setFirstUseRequired(false);
    void loadDashboard();
  }

  function openCardsFromFirstUse() {
    setFirstUseRequired(false);
    setFinanceFocusTarget(null);
    navigateTo("finance", "cards");
    void loadDashboard();
  }

  useEffect(() => {
    const element = scrollRef.current;
    if (element && (messages.length > 0 || activeTool)) {
      element.scrollTop = element.scrollHeight;
    }
  }, [messages, activeTool]);

  useEffect(() => {
    if (editingConversationId) conversationRenameRef.current?.focus();
  }, [editingConversationId]);

  async function selectConversation(id: string) {
    setError("");
    setFinanceFocusTarget(null);
    navigateTo("chat");
    setMobileMenuOpen(false);
    setContextPanelOpen(false);
    setMessages([]);
    setConversationMenuId(null);
    setEditingConversationId(null);
    try {
      await loadConversation(id);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Não foi possível abrir a conversa.");
    }
  }

  function startConversation() {
    setError("");
    setFinanceFocusTarget(null);
    navigateTo("chat");
    setMobileMenuOpen(false);
    setContextPanelOpen(false);
    setConversationMenuId(null);
    setEditingConversationId(null);
    setConversationId(null);
    setMessages([]);
    setDraft("");
    composerRef.current?.focus();
  }

  function updateAssistantMessage(id: string, update: (message: AssistantMessage) => AssistantMessage) {
    setMessages((current) => current.map((message) => (message.id === id ? update(message) : message)));
  }

  async function sendMessage(content: string, imageDataUrls: string[] = []) {
    const clean = content.trim();
    const messageContent = clean || (imageDataUrls.length ? "Analise estas imagens financeiras em conjunto e me diga o que encontrou." : "");
    if (!messageContent || sending || status?.configured !== true) return;
    if (imageDataUrls.length && status.provider !== "chatgpt_plan") {
      setError("A análise de imagens está disponível quando o ChatGPT conectado estiver ativo.");
      return;
    }
    if (imageDataUrls.length > 4) {
      setAttachedImageError("Envie no máximo 4 imagens por mensagem.");
      return;
    }
    const requestBody = JSON.stringify({ content: messageContent, ...(imageDataUrls.length ? { image_data_urls: imageDataUrls } : {}) });
    if (new TextEncoder().encode(requestBody).byteLength > 12_500_000) {
      setAttachedImageError("As imagens juntas excedem o limite da mensagem. Remova uma imagem ou escolha versões menores.");
      return;
    }
    setError("");
    const requestController = new AbortController();
    activeRequestControllerRef.current = requestController;
    setSending(true);
    setResponseProgress(pendingLabelFor(messageContent));
    setActiveTool("");
    let activeConversationId = conversationId;
    let optimisticMessageIds: [string, string] | null = null;
    let responseAccepted = false;
    let chatRequestKey: { key: string; storageKey: string } | null = null;
    let responseCompleted = false;
    try {
      if (!activeConversationId) {
        const created = await apiRequest<Conversation & { messages: AssistantMessage[] }>(
          "/api/ai/conversations",
          { method: "POST", body: JSON.stringify({}) },
        );
        if (requestController.signal.aborted) throw new DOMException("Resposta interrompida", "AbortError");
        activeConversationId = created.id;
        setConversationId(created.id);
      }
      chatRequestKey = await chatRequestIdempotencyKey(activeConversationId, requestBody);

      const userMessage: AssistantMessage = {
        id: createOptimisticMessageId(),
        role: "USER",
        content: messageContent,
        imagePreviews: imageDataUrls.length
          ? imageDataUrls.map((dataUrl) => ({ id: crypto.randomUUID(), dataUrl }))
          : undefined,
        structured_content: imageDataUrls.length ? imageDataUrls.map(() => ({ type: "image_attachment", data: { stored: false } })) : undefined,
      };
      const assistantId = createOptimisticMessageId();
      optimisticMessageIds = [userMessage.id, assistantId];
      setMessages((current) => [
        ...current,
        userMessage,
        { id: assistantId, role: "ASSISTANT", content: "", pending: true },
      ]);

      const response = await fetch(`/api/ai/conversations/${activeConversationId}/messages`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-SophIA-Request": "1",
          "Idempotency-Key": chatRequestKey.key,
          Accept: "text/event-stream",
        },
        body: requestBody,
        cache: "no-store",
        signal: requestController.signal,
      });
      if (!response.ok) {
        let message = "Não foi possível enviar a mensagem.";
        try {
          const body: unknown = await response.json();
          message = stringValue(record(body)?.detail) ?? message;
        } catch {
          // Respostas sem JSON mantêm a mensagem genérica.
        }
        throw new ApiError(message, response.status);
      }
      responseAccepted = true;
      setDraft("");
      setAttachedImages([]);
      setAttachedImageError("");
      if (composerRef.current) composerRef.current.style.height = "42px";
      if (!response.body) throw new Error("A resposta do assistente veio vazia.");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let streamDone = false;
      while (!streamDone) {
        const chunk = await reader.read();
        streamDone = chunk.done;
        buffer += decoder.decode(chunk.value, { stream: !chunk.done });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const eventName = frame.match(/^event:\s*(.+)$/m)?.[1]?.trim();
          const dataLine = frame.split("\n").find((line) => line.startsWith("data:"));
          if (!eventName || !dataLine) continue;
          let payload: Record<string, unknown>;
          try {
            const parsed: unknown = JSON.parse(dataLine.slice(5).trim());
            payload = record(parsed) ?? {};
          } catch {
            continue;
          }
          if (eventName === "text_delta") {
            const text = stringValue(payload.text) ?? "";
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              content: message.content + text,
            }));
          } else if (eventName === "reset") {
            updateAssistantMessage(assistantId, (message) => ({ ...message, content: "" }));
          } else if (eventName === "replace") {
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              content: stringValue(payload.text) ?? message.content,
            }));
          } else if (eventName === "structured") {
            const items = Array.isArray(payload.items) ? (payload.items as StructuredItem[]) : [];
            updateAssistantMessage(assistantId, (message) => ({ ...message, structured_content: items }));
          } else if (eventName === "conversation_title") {
            const title = stringValue(payload.title);
            if (title) {
              setConversations((current) => current.map((item) =>
                item.id === activeConversationId ? { ...item, title } : item,
              ));
            }
          } else if (eventName === "tool_status") {
            const name = stringValue(payload.name) ?? "uma ferramenta financeira";
            const toolStatus = stringValue(payload.status);
            setActiveTool(
              toolStatus === "running"
                ? `Consultando ${toolLabel(name)}…`
                : toolStatus === "complete"
                  ? "Organizando os resultados…"
                  : "",
            );
          } else if (eventName === "done") {
            setActiveTool("");
            responseCompleted = payload.status === "ok" || payload.status === "confirmation_required";
          }
        }
      }

      await Promise.all([loadConversation(activeConversationId), loadConversations(), loadDashboard()]);
      if (responseCompleted && chatRequestKey) {
        window.sessionStorage.removeItem(chatRequestKey.storageKey);
      }
    } catch (sendError) {
      if (isAbortError(sendError)) {
        const assistantId = optimisticMessageIds?.[1];
        if (assistantId) {
          updateAssistantMessage(assistantId, (message) => ({
            ...message,
            pending: false,
            interrupted: true,
          }));
        }
        return;
      }
      const message = sendError instanceof Error ? sendError.message : "Não foi possível concluir a mensagem.";
      setError(message);
      const failedMessageIds = optimisticMessageIds;
      if (responseAccepted) {
        setMessages((current) => current.filter((item) => !item.pending));
      } else if (failedMessageIds) {
        setMessages((current) => current.filter((item) => !failedMessageIds.includes(item.id)));
      }
    } finally {
      if (activeRequestControllerRef.current === requestController) {
        activeRequestControllerRef.current = null;
      }
      setActiveTool("");
      setResponseProgress("");
      setSending(false);
    }
  }

  function stopGenerating() {
    activeRequestControllerRef.current?.abort();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await sendMessage(draft, attachedImages.map((image) => image.dataUrl));
  }

  async function prepareChatImages(files: File[]) {
    if (!files.length) return;
    setAttachedImageError("");
    if (status?.provider !== "chatgpt_plan") {
      setAttachedImageError("A análise de imagens funciona com o ChatGPT conectado.");
      return;
    }
    if (attachedImages.length + files.length > 4) {
      setAttachedImageError("Envie no máximo 4 imagens por mensagem.");
      return;
    }
    try {
      const preparedImages: string[] = [];
      for (const file of files) {
        if (!(file.type === "image/jpeg" || file.type === "image/png" || file.type === "image/webp")) {
          throw new Error("Escolha imagens JPEG, PNG ou WebP.");
        }
        if (file.size > 25 * 1024 * 1024) throw new Error("Cada imagem precisa ter até 25 MB.");
        const bitmap = await createImageBitmap(file);
        if (bitmap.width * bitmap.height > 48_000_000) {
          bitmap.close();
          throw new Error("Uma imagem excede 48 megapixels. Envie uma versão reduzida.");
        }
        const scale = Math.min(1, 2048 / Math.max(bitmap.width, bitmap.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        const context = canvas.getContext("2d");
        if (!context) {
          bitmap.close();
          throw new Error("Não foi possível preparar uma das imagens.");
        }
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close();
        const normalized = canvas.toDataURL("image/webp", 0.82);
        if (normalized.length > 3_000_000) throw new Error("Não foi possível reduzir uma imagem o suficiente. Tente uma captura menor.");
        preparedImages.push(normalized);
      }
      setAttachedImages((current) => [
        ...current,
        ...preparedImages.map((dataUrl) => ({ id: crypto.randomUUID(), dataUrl })),
      ]);
    } catch (imageError) {
      setAttachedImageError(imageError instanceof Error ? imageError.message : "Não foi possível ler essa imagem.");
    }
  }

  async function selectChatImage(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = "";
    await prepareChatImages(files);
  }

  function handleComposerPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const imageItems = Array.from(event.clipboardData.items).filter(
      (item) => item.kind === "file" && item.type.startsWith("image/"),
    );
    if (!imageItems.length) return;

    event.preventDefault();
    void prepareChatImages(imageItems.map((item) => item.getAsFile()).filter((file): file is File => file !== null));
  }

  function handleComposerKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    const isMobile = window.matchMedia("(max-width: 760px)").matches;
    if (event.key === "Enter" && !event.shiftKey && !isMobile) {
      event.preventDefault();
      void sendMessage(draft, attachedImages.map((image) => image.dataUrl));
    }
  }

  async function handlePendingAction(id: string, action: "confirm" | "cancel") {
    if (!conversationId) return;
    setPendingAction({ id, action });
    setError("");
    try {
      await apiRequest(
        `/api/ai/conversations/${conversationId}/tool-calls/${id}/${action}`,
        { method: "POST" },
      );
      await Promise.all([loadConversation(conversationId), loadConversations(), loadDashboard()]);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Não foi possível concluir a ação.");
    } finally {
      setPendingAction(null);
    }
  }

  function openSettings() {
    setFinanceFocusTarget(null);
    navigateTo("settings");
    setMobileMenuOpen(false);
    setContextPanelOpen(false);
    void loadSettings();
  }

  async function deleteMemory(id: string) {
    try {
      await apiRequest<void>(`/api/ai/memories/${id}`, { method: "DELETE" });
      setMemories((current) => current.filter((memory) => memory.id !== id));
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Não foi possível remover a preferência.");
    }
  }

  async function saveMemory(content: string, id: string | null) {
    const saved = await apiRequest<Memory>(
      id ? `/api/ai/memories/${id}` : "/api/ai/memories",
      {
        method: id ? "PATCH" : "POST",
        body: JSON.stringify({ content }),
      },
    );
    setMemories((current) =>
      id
        ? current.map((memory) => (memory.id === id ? saved : memory))
        : [saved, ...current],
    );
  }

  function beginRenameConversation(conversation: Conversation) {
    setConversationMenuId(null);
    setEditingConversationId(conversation.id);
    setConversationTitleDraft(conversation.title);
  }

  async function saveConversationTitle(id: string) {
    const title = conversationTitleDraft.trim();
    if (!title || busyConversationId) return;
    setBusyConversationId(id);
    setError("");
    try {
      const updated = await apiRequest<Conversation>(`/api/ai/conversations/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      });
      setConversations((current) => current.map((item) => item.id === id ? updated : item));
      setEditingConversationId(null);
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : "Não foi possível renomear a conversa.");
    } finally {
      setBusyConversationId(null);
    }
  }

  async function archiveConversation(conversation: Conversation) {
    if (!window.confirm(`Arquivar a conversa “${conversation.title}”?`)) return;
    setBusyConversationId(conversation.id);
    setConversationMenuId(null);
    setError("");
    try {
      await apiRequest<void>(`/api/ai/conversations/${conversation.id}/archive`, { method: "POST" });
      setConversations((current) => current.filter((item) => item.id !== conversation.id));
      if (conversationId === conversation.id) {
        setConversationId(null);
        setMessages([]);
        setDraft("");
        setContextPanelOpen(false);
      }
    } catch (archiveError) {
      setError(archiveError instanceof Error ? archiveError.message : "Não foi possível arquivar a conversa.");
    } finally {
      setBusyConversationId(null);
    }
  }

  function chooseNavigation(item: (typeof NAV_ITEMS)[number]) {
    setError("");
    setFinanceFocusTarget(null);
    setConversationMenuId(null);
    setEditingConversationId(null);
    if (item.view === "settings") {
      void openSettings();
    } else {
      navigateTo(item.view, item.section ?? financeSection);
      setMobileMenuOpen(false);
    }
  }

  function openForecast(item?: Dashboard["forecast_items"][number]) {
    setError("");
    if (item) {
      const separator = item.id.indexOf(":");
      financeFocusRequestId.current += 1;
      setFinanceFocusTarget({
        source: item.source,
        id: separator >= 0 ? item.id.slice(separator + 1) : item.id,
        credit_card_id: item.credit_card_id,
        request_id: financeFocusRequestId.current,
      });
      navigateTo("finance", item.source === "CARD_INVOICE" ? "cards" : "recurrences");
    } else {
      setFinanceFocusTarget(null);
      navigateTo("finance", "overview");
    }
    setMobileMenuOpen(false);
    setContextPanelOpen(false);
    void loadDashboard();
  }

  function openAccount() {
    setFinanceFocusTarget(null);
    navigateTo("account");
    setMobileMenuOpen(false);
    setContextPanelOpen(false);
    setConversationMenuId(null);
    setEditingConversationId(null);
    setError("");
  }

  const currentNav = activeNav(view, financeSection);
  const firstName = displayName.trim().split(/\s+/)[0] || displayName;
  const latestUserMessage = [...messages].reverse().find((message) => message.role === "USER")?.content ?? "";
  const contextMessage = [...messages].reverse().find((message) =>
    message.role === "USER" && contextMode(message.content, contextCards, contextAccounts) !== "overview",
  )?.content ?? latestUserMessage;
  const hasUsefulContext = Boolean(contextMessage && contextMode(contextMessage, contextCards, contextAccounts) !== "overview");
  const showWelcome = messages.length === 0 && !loading;
  const hasHomeSummary = Boolean(dashboard && (
    contextAccounts.length > 0 ||
    dashboard.monthly_expenses !== "0.00" ||
    dashboard.recent_transactions.length > 0
  ));
  const contextPanelAvailable = hasUsefulContext || (showWelcome && hasHomeSummary);
  useEffect(() => {
    if (window.matchMedia("(max-width: 1120px)").matches) {
      setContextPanelOpen(false);
      return;
    }
    setContextPanelOpen(Boolean(contextPanelAvailable && (showWelcome || hasUsefulContext)));
  }, [contextPanelAvailable, showWelcome, hasUsefulContext]);
  useEffect(() => {
    const mobile = window.matchMedia("(max-width: 1120px)");
    const closeContextOnMobile = (event: MediaQueryListEvent) => {
      if (event.matches) setContextPanelOpen(false);
    };
    mobile.addEventListener("change", closeContextOnMobile);
    return () => mobile.removeEventListener("change", closeContextOnMobile);
  }, []);
  const contextSuggestions = [
    {
      title: "Meu mês",
      detail: "Gastos e categorias",
      message: "Quanto gastei neste mês?",
      icon: ChartNoAxesCombined,
    },
    contextCards[0] && {
      title: `Fatura ${contextCards[0].name}`,
      detail: "Vencimento e limite",
      message: `Como está a fatura do ${contextCards[0].name}?`,
      icon: CreditCard,
    },
    contextAccounts[0] && {
      title: `Saldo ${contextAccounts[0].name}`,
      detail: "Saldo e movimentações",
      message: `Qual o saldo da conta ${contextAccounts[0].name}?`,
      icon: Landmark,
    },
    {
      title: "Movimentações",
      detail: "Entradas, despesas e transferências",
      message: "Quais foram minhas movimentações recentes?",
      icon: ReceiptText,
    },
  ].filter((suggestion): suggestion is NonNullable<typeof suggestion> => Boolean(suggestion)).slice(0, 3);
  const aiAvailable = status?.configured === true;
  const providerPausedNotice = status?.configured === false ? (
    <aside aria-label="Assistente pausado" className="assistant-provider-note">
      <p><strong>{status.provider === "ollama" ? "IA local indisponível no momento." : "Plano ChatGPT ainda não conectado."}</strong> {status.provider === "ollama" ? "O modelo local da SophIA ainda não está pronto na VM." : "Conecte sua conta pelo procedimento seguro descrito no README. A SophIA não usará uma API paga como alternativa."} Seus registros manuais continuam disponíveis.</p>
      <button className="assistant-provider-action" onClick={() => chooseNavigation(NAV_ITEMS[1])} type="button"><ReceiptText aria-hidden="true" size={15} />Abrir lançamentos</button>
    </aside>
  ) : null;
  const composer = aiAvailable ? (
    <form className={showWelcome ? "assistant-composer assistant-composer-inline" : "assistant-composer"} onSubmit={(event) => void handleSubmit(event)}>
      <input accept="image/jpeg,image/png,image/webp" aria-label="Anexar fotos" className="assistant-attachment-input" multiple onChange={(event) => void selectChatImage(event)} ref={attachmentInputRef} type="file" />
      {attachedImages.length > 0 && <div className="assistant-attachment-preview"><div className="assistant-attachment-thumbnails">{attachedImages.map((image, index) => <div className="assistant-attachment-thumbnail" key={image.id}><Image alt={`Prévia da imagem ${index + 1}`} height={52} src={image.dataUrl} unoptimized width={52} /><button aria-label={`Remover imagem ${index + 1}`} onClick={() => { setAttachedImages((current) => current.filter((item) => item.id !== image.id)); setAttachedImageError(""); }} type="button"><X aria-hidden="true" size={14} /></button></div>)}</div><span>{attachedImages.length} {attachedImages.length === 1 ? "imagem pronta" : "imagens prontas"} para análise<span>Serão enviadas ao ChatGPT conectado e removidas do armazenamento após a análise.</span></span></div>}
      {attachedImageError && <p className="assistant-attachment-error" role="alert">{attachedImageError}</p>}
      <textarea
        aria-label="Mensagem para o assistente"
        disabled={sending || loading}
        onChange={(event) => {
          const textarea = event.currentTarget;
          textarea.style.height = "auto";
          textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
          setDraft(textarea.value);
        }}
        onKeyDown={handleComposerKeyDown}
        onPaste={handleComposerPaste}
        placeholder="Pergunte sobre suas finanças…"
        ref={composerRef}
        rows={1}
        value={draft}
      />
      <div className="assistant-composer-footer">
        <span id="assistant-composer-hint"><span className="composer-hint-desktop">Até 4 imagens · Ctrl/⌘ + V cola imagens · Enter envia</span><span className="composer-hint-mobile">Até 4 imagens · Enter quebra linha · botão envia</span></span>
        <div className="assistant-composer-actions">
          <button aria-label="Anexar foto para análise" className="assistant-attach-button" disabled={sending || status?.provider !== "chatgpt_plan"} onClick={() => attachmentInputRef.current?.click()} title={status?.provider === "chatgpt_plan" ? "Anexar foto" : "Fotos funcionam com o ChatGPT conectado"} type="button"><ImagePlus aria-hidden="true" size={18} /></button>
          {sending
            ? <button aria-label="Parar resposta" className="assistant-stop-button" onClick={stopGenerating} title="Parar a resposta" type="button"><Square aria-hidden="true" fill="currentColor" size={14} /></button>
            : <button aria-label="Enviar mensagem" disabled={!draft.trim() && attachedImages.length === 0} type="submit"><ArrowUp aria-hidden="true" size={19} /></button>}
        </div>
      </div>
    </form>
  ) : null;

  function toggleDesktopSidebar() {
    setSidebarCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem("sophia-sidebar-collapsed", String(next));
      return next;
    });
  }

  function reloadApplication() {
    if (sending || refreshingApp) return;
    if ((draft.trim() || attachedImages.length > 0) && !window.confirm("O texto e as imagens ainda não enviados serão descartados ao recarregar. Deseja continuar?")) return;
    try {
      const snapshot: WorkspaceRefreshSnapshot = {
        version: 1,
        view,
        financeSection,
        conversationId: view === "chat" ? conversationId : null,
      };
      window.sessionStorage.setItem(WORKSPACE_REFRESH_SNAPSHOT_KEY, JSON.stringify(snapshot));
    } catch {
      // O recarregamento continua disponível mesmo se o navegador bloquear o armazenamento da sessão.
    }
    setRefreshingApp(true);
    window.location.reload();
  }

  useEffect(() => {
    setSidebarCollapsed(window.localStorage.getItem("sophia-sidebar-collapsed") === "true");
  }, []);

  if (firstUseRequired === true) {
    return (
      <div data-theme={theme}>
        <FirstUseSetup
          displayName={displayName}
          onComplete={completeFirstUse}
          onOpenCards={openCardsFromFirstUse}
        />
      </div>
    );
  }

  if (firstUseRequired === null && loading) {
    return <main className="auth-page" role="status">Preparando seu espaço financeiro…</main>;
  }

  return (
    <div className={sidebarCollapsed ? "assistant-layout sidebar-collapsed" : "assistant-layout"} data-theme={theme} onTouchEnd={handleSidebarTouchEnd} onTouchStart={handleSidebarTouchStart} ref={layoutRef}>
      <a className="skip-link" href="#assistant-main-content">Pular para o conteúdo principal</a>
      {mobileMenuOpen && <button aria-label="Fechar menu" className="assistant-backdrop" onClick={() => setMobileMenuOpen(false)} tabIndex={-1} type="button" />}
      {contextPanelOpen && contextPanelAvailable && <button aria-label="Fechar contexto" className="assistant-context-backdrop" onClick={() => setContextPanelOpen(false)} type="button" />}
      <aside
        aria-label="Navegação principal"
        className={mobileMenuOpen ? "assistant-sidebar mobile-open" : "assistant-sidebar"}
        id="primary-navigation-drawer"
        ref={sidebarRef}
      >
        <button aria-label="Ir para a visão geral" className="assistant-brand" onClick={() => chooseNavigation(NAV_ITEMS[0])} type="button">
          <BrandMark />
          <span className="assistant-brand-name">SophIA</span>
        </button>
        <button aria-label={sidebarCollapsed ? "Expandir menu lateral" : "Recolher menu lateral"} aria-pressed={sidebarCollapsed} className="assistant-sidebar-toggle" onClick={toggleDesktopSidebar} title={sidebarCollapsed ? "Expandir menu lateral" : "Recolher menu lateral"} type="button">
          {sidebarCollapsed ? <PanelLeftOpen aria-hidden="true" size={16} /> : <PanelLeftClose aria-hidden="true" size={16} />}
          <span>{sidebarCollapsed ? "Expandir menu" : "Recolher menu"}</span>
        </button>
        <button
          aria-label="Nova conversa"
          className="assistant-new-chat"
          onClick={startConversation}
          title="Nova conversa"
          type="button"
        >
          <Plus aria-hidden="true" size={17} strokeWidth={2} /><span>Nova conversa</span>
        </button>
        <button
          aria-busy={refreshingApp}
          aria-label="Recarregar aplicativo"
          className={refreshingApp ? "assistant-sidebar-refresh is-refreshing" : "assistant-sidebar-refresh"}
          disabled={sending || refreshingApp}
          onClick={reloadApplication}
          title={sending ? "Aguarde a resposta terminar antes de recarregar" : "Recarregar aplicativo"}
          type="button"
        >
          <RefreshCw aria-hidden="true" size={15} />
          <span>Atualizar aplicativo</span>
        </button>
        <div className="assistant-history" onScroll={loadMoreConversationsOnScroll}>
          <p>Conversas recentes</p>
          {loading ? <span className="history-placeholder">Carregando…</span> : conversations.length === 0 ? (
            <span className="history-placeholder">Pergunte sobre seus gastos para começar.</span>
          ) : conversations.slice(0, visibleConversationCount).map((conversation) => (
            <div className={conversation.id === conversationId && view === "chat" ? "history-row current" : "history-row"} key={conversation.id}>
              {editingConversationId === conversation.id ? (
                <form className="history-rename-form" onSubmit={(event) => { event.preventDefault(); void saveConversationTitle(conversation.id); }}>
                  <input aria-label="Nome da conversa" maxLength={120} onChange={(event) => setConversationTitleDraft(event.target.value)} ref={conversationRenameRef} value={conversationTitleDraft} />
                  <button aria-label="Salvar nome" disabled={busyConversationId === conversation.id || !conversationTitleDraft.trim()} type="submit">✓</button>
                  <button aria-label="Cancelar renomeação" onClick={() => setEditingConversationId(null)} type="button">×</button>
                </form>
              ) : <>
                <button
                  aria-current={conversation.id === conversationId && view === "chat" ? "page" : undefined}
                  className="history-item"
                  onClick={() => void selectConversation(conversation.id)}
                  title={conversation.title}
                  type="button"
                >
                  <MessageSquare className="history-marker" aria-hidden="true" size={14} strokeWidth={1.8} />
                  <span className="history-title">{conversation.title}</span>
                </button>
                <div className="history-actions">
                  <button aria-expanded={conversationMenuId === conversation.id} aria-label={`Ações da conversa ${conversation.title}`} className="history-action-toggle" disabled={busyConversationId === conversation.id} onClick={() => setConversationMenuId((current) => current === conversation.id ? null : conversation.id)} title="Ações da conversa" type="button"><MoreHorizontal aria-hidden="true" size={17} /></button>
                  {conversationMenuId === conversation.id && <div className="history-action-menu">
                    <button onClick={() => beginRenameConversation(conversation)} type="button"><Pencil aria-hidden="true" size={14} />Renomear</button>
                    <button onClick={() => void archiveConversation(conversation)} type="button"><Archive aria-hidden="true" size={14} />Arquivar</button>
                  </div>}
                </div>
              </>}
            </div>
          ))}
          {!loading && conversations.length > CONVERSATION_HISTORY_BATCH_SIZE && <span aria-atomic="true" aria-live="polite" className="sr-only">
            Histórico: {Math.min(visibleConversationCount, conversations.length)} de {conversations.length} conversas exibidas.
          </span>}
        </div>
        <nav className="assistant-nav" aria-label="Navegação financeira">
          <div className="assistant-nav-group">
            <p className="assistant-nav-label">Finanças</p>
            {NAV_ITEMS.filter((item) => item.view === "finance").map((item) => {
              const key = item.view === "finance" ? `finance-${item.section}` : item.view;
              return (
                <button
                  aria-current={currentNav === key ? "page" : undefined}
                  aria-label={item.label}
                  className={currentNav === key ? "assistant-nav-item selected" : "assistant-nav-item"}
                  key={key}
                  onClick={() => chooseNavigation(item)}
                    title={item.label}
                  type="button"
                >
                  <item.icon aria-hidden="true" size={17} strokeWidth={1.8} /><span className="assistant-nav-item-label">{item.label}</span>
                </button>
              );
            })}
          </div>
          <div className="assistant-nav-group assistant-nav-preferences">
            <p className="assistant-nav-label">Preferências</p>
            {NAV_ITEMS.filter((item) => item.view === "settings").map((item) => {
            const key = item.view === "finance" ? `finance-${item.section}` : item.view;
            return (
              <button
                aria-current={currentNav === key ? "page" : undefined}
                aria-label={item.label}
                className={currentNav === key ? "assistant-nav-item selected" : "assistant-nav-item"}
                key={key}
                onClick={() => chooseNavigation(item)}
                title={item.label}
                type="button"
              >
                <item.icon aria-hidden="true" size={17} strokeWidth={1.8} /><span className="assistant-nav-item-label">{item.label}</span>
              </button>
            );
            })}
          </div>
        </nav>
        <div className="assistant-account">
          <button aria-current={view === "account" ? "page" : undefined} aria-label={`Minha conta de ${displayName}`} className={view === "account" ? "assistant-account-trigger selected" : "assistant-account-trigger"} onClick={openAccount} title="Minha conta" type="button">
            <span className="assistant-avatar" aria-hidden="true">{avatarUrl ? <Image alt="" decoding="async" height={36} src={avatarUrl} unoptimized width={36} /> : displayName.slice(0, 1).toUpperCase()}</span>
            <span className="assistant-account-name">{displayName}</span>
          </button>
          <button aria-label="Sair" className="assistant-logout" onClick={onLogout} title="Sair" type="button"><LogOut aria-hidden="true" size={16} /></button>
        </div>
      </aside>

      <main className="assistant-main" id="assistant-main-content" inert={mobileMenuOpen} tabIndex={-1}>
        <header className="assistant-topbar">
          <button aria-controls="primary-navigation-drawer" aria-expanded={mobileMenuOpen} aria-label="Abrir menu de navegação" className="assistant-menu-toggle" onClick={() => setMobileMenuOpen(true)} ref={menuToggleRef} type="button"><Menu aria-hidden="true" size={20} /></button>
          <div className="assistant-topbar-title">
            <strong>{view === "chat" ? conversations.find((conversation) => conversation.id === conversationId)?.title ?? "Nova conversa" : view === "settings" ? "Preferências" : view === "account" ? "Minha conta" : "Finanças"}</strong>
            <span>{view === "chat" ? "SophIA · sua assistente financeira" : view === "account" ? "Perfil, segurança e sessões" : "Dados calculados pelo sistema"}</span>
          </div>
          <div className="assistant-topbar-actions">
            <DueNotifications dashboard={dashboard} openForecast={openForecast} refreshDashboard={() => void loadDashboard()} />
            {view === "chat" && contextPanelAvailable && (
              <button
                aria-expanded={contextPanelOpen}
                aria-label={contextPanelOpen ? "Recolher contexto financeiro" : "Abrir contexto financeiro"}
                className="assistant-context-toggle"
                onClick={() => setContextPanelOpen((open) => !open)}
                title="Contexto financeiro"
                type="button"
              >
                <WalletCards aria-hidden="true" size={16} />
                <span>Contexto</span>
              </button>
            )}
            <button
              aria-label={theme === "light" ? "Ativar tema escuro" : "Ativar tema claro"}
              className="assistant-theme-toggle"
              onClick={() => onThemeChange(theme === "light" ? "dark" : "light")}
              title={theme === "light" ? "Ativar tema escuro" : "Ativar tema claro"}
              type="button"
            >
              {theme === "light" ? <Moon aria-hidden="true" size={17} /> : <Sun aria-hidden="true" size={17} />}
              <span>{theme === "light" ? "Escuro" : "Claro"}</span>
            </button>
            <div className={`assistant-connection ${aiAvailable ? "connected" : status ? "paused" : "checking"}`}>
              <span aria-hidden="true" />{aiAvailable ? status?.provider === "ollama" ? "IA local" : "ChatGPT Plus" : status ? "IA pausada" : "Verificando IA"}
            </div>
          </div>
        </header>

        {error && <div className="assistant-error" role="alert">{error}<button onClick={() => setError("")} type="button">Fechar</button></div>}

        {view === "finance" ? (
          <div className="assistant-finance-view">
            <FinanceWorkspace
              displayName={displayName}
              embedded
              focusTarget={financeFocusTarget}
              initialSection={financeSection}
              onSectionChange={(section) => navigateTo("finance", section)}
              onOpenAssistant={(prompt) => { startConversation(); setDraft(prompt); }}
              onLogout={onLogout}
            />
          </div>
        ) : view === "settings" ? (
          <SettingsView
            loading={loadingSettings}
            email={email}
            memories={memories}
            accounts={contextAccounts}
            cards={contextCards}
            onDeleteMemory={(id) => void deleteMemory(id)}
            onSaveMemory={saveMemory}
            onThemeChange={onThemeChange}
            status={status}
            theme={theme}
            usage={usage}
            diagnostics={diagnostics}
          />
        ) : view === "account" ? (
          <AccountView
            avatarUrl={avatarUrl}
            displayName={displayName}
            email={email}
            mfaRequired={mfaRequired}
            mfaEnrolled={mfaEnrolled}
            onAvatarUrlChange={onAvatarUrlChange}
            onDisplayNameChange={onDisplayNameChange}
            onLogout={onLogout}
          />
        ) : (
          <div className={contextPanelAvailable && contextPanelOpen ? "assistant-chat-layout" : "assistant-chat-layout context-hidden"}>
            <section aria-label="Conversa com a SophIA" className="assistant-chat-column">
              <div className="assistant-message-list" ref={scrollRef}>
                {showWelcome ? (
                  <div className="assistant-welcome">
                    <p className="assistant-welcome-label">FINANÇAS PESSOAIS</p>
                    <h1>{greeting}, {firstName}.</h1>
                    <p className="assistant-welcome-copy">Como posso ajudar com suas finanças hoje?</p>
                    {dashboard && (contextAccounts.length > 0 || dashboard.monthly_expenses !== "0.00") && (
                      <div className="assistant-home-summary">
                        {contextAccounts.length > 0 && dashboard.checking_balance !== null && <span>Saldo em contas correntes <strong>{formatCurrency(dashboard.checking_balance)}</strong></span>}
                        {contextAccounts.length > 0 && dashboard.checking_balance === null && (
                          <span>Saldo em contas correntes <strong>{dashboard.incomplete_checking_account_count > 0 ? "Incompleto" : "Não cadastrado"}</strong><small>{dashboard.incomplete_checking_account_count} {dashboard.incomplete_checking_account_count === 1 ? "conta corrente precisa" : "contas correntes precisam"} de saldo inicial e data-base</small></span>
                        )}
                        {dashboard.account_type_balances.filter((group) => group.account_type !== "CHECKING").map((group) => <span key={group.account_type}>Saldo em {accountTypeLabel(group.account_type).toLocaleLowerCase("pt-BR")} <strong>{group.balance === null ? "Pendente" : formatCurrency(group.balance)}</strong></span>)}
                        <span>Gastos no mês <strong>{formatCurrency(dashboard.monthly_expenses)}</strong></span>
                      </div>
                    )}
                    {aiAvailable && <>
                      <p className="assistant-suggestions-label">Sugestões</p>
                      <div className="assistant-suggestions">
                        {contextSuggestions.map((suggestion) => (
                          <button key={suggestion.title} onClick={() => void sendMessage(suggestion.message)} type="button">
                            <span className="suggestion-index" aria-hidden="true"><suggestion.icon size={18} strokeWidth={1.8} /></span>
                            <span className="suggestion-copy"><strong>{suggestion.title}</strong><small>{suggestion.detail}</small></span>
                            <ArrowUp aria-hidden="true" className="suggestion-arrow" size={16} />
                          </button>
                        ))}
                      </div>
                    </>}
                    {providerPausedNotice}
                    {composer}
                  </div>
                ) : messages.map((message) => (
                  <MessageBubble
                    key={message.id}
                    message={message}
                    pendingLabel={activeTool || responseProgress}
                    onStop={stopGenerating}
                    onPendingAction={(id, action) => void handlePendingAction(id, action)}
                    pendingAction={pendingAction}
                  />
                ))}
              </div>
              {!showWelcome && providerPausedNotice}
              {!showWelcome && composer}
            </section>
            {contextPanelAvailable && contextPanelOpen && <ContextPanel
              accounts={contextAccounts}
              cards={contextCards}
              dashboard={dashboard}
              latestUserMessage={contextMessage}
              mobileOpen={contextPanelOpen}
              onClose={() => setContextPanelOpen(false)}
            />}
          </div>
        )}
      </main>
    </div>
  );
}

function toolLabel(name: string): string {
  const labels: Record<string, string> = {
    get_month_summary: "o resumo do mês",
    get_month_forecast: "as contas previstas do mês",
    get_category_breakdown: "as categorias",
    get_transactions: "os lançamentos",
    search_transactions: "seus lançamentos",
    get_accounts: "suas contas",
    get_account_balance: "o saldo da conta",
    get_credit_cards: "seus cartões",
    get_invoice: "a fatura",
    create_transaction: "seu lançamento",
    create_transfer: "a transferência",
    create_card_purchase: "a compra no cartão",
  };
  return labels[name] ?? "seus dados financeiros";
}

function pendingLabelFor(content: string): string {
  const normalized = normalizeForMatch(content);
  if (/(gasto|gastei|despesa|categoria|combustivel|alimentacao|mercado)/.test(normalized)) {
    return "Preparando a consulta dos seus gastos…";
  }
  if (/(fatura|cartao|limite)/.test(normalized)) return "Preparando a consulta da fatura…";
  if (/(saldo|conta|extrato)/.test(normalized)) return "Preparando a consulta do saldo…";
  if (/(receita|recebi|salario|entrada)/.test(normalized)) return "Preparando a consulta das receitas…";
  return "Entendendo seu pedido…";
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error && error.name === "AbortError";
}

function MessageBubble({
  message,
  pendingLabel,
  onStop,
  onPendingAction,
  pendingAction,
}: {
  message: AssistantMessage;
  pendingLabel: string;
  onStop: () => void;
  onPendingAction: (id: string, action: "confirm" | "cancel") => void;
  pendingAction: PendingAction;
}) {
  const userMessage = message.role === "USER";
  return (
    <article className={userMessage ? "assistant-message user-message" : "assistant-message model-message"}>
      {!userMessage && <BrandMark className="message-avatar" size={27} />}
      <div className="message-body">
        <div className="message-author">{userMessage ? "Você" : "SophIA"}</div>
        {message.content && <p className="message-text">{userMessage ? message.content : renderAssistantText(message.content)}</p>}
        {message.imagePreviews?.length ? <div className="assistant-message-images">{message.imagePreviews.map((image, index) => <Image alt={`Imagem ${index + 1} enviada para análise`} className="assistant-message-image" height={240} key={image.id} src={image.dataUrl} unoptimized width={420} />)}</div> : userMessage && message.structured_content?.some((item) => item.type === "image_attachment") ? <span className="assistant-image-not-stored">{message.structured_content.filter((item) => item.type === "image_attachment").length} {message.structured_content.filter((item) => item.type === "image_attachment").length === 1 ? "imagem analisada" : "imagens analisadas"} e removidas do armazenamento da conversa.</span> : null}
        {message.pending && <div aria-live="polite" className="assistant-pending-card" role="status">
          <span aria-hidden="true" className="assistant-pending-icon"><LoaderCircle size={20} strokeWidth={2} /></span>
          <span className="assistant-pending-copy"><strong>{pendingLabel || "Preparando sua resposta…"}</strong><small>A SophIA está trabalhando nos seus dados.</small></span>
          <button aria-label="Parar resposta" className="assistant-stop-inline" onClick={onStop} title="Parar a resposta" type="button"><Square aria-hidden="true" fill="currentColor" size={12} /><span>Parar</span></button>
        </div>}
        {message.interrupted && <p className="assistant-interrupted-note" role="status">Resposta interrompida por você.</p>}
        {message.structured_content?.map((item) => (
          <StructuredCard
            item={item}
            key={`${message.id}-${item.tool_call_id ?? `${item.type}-${item.snapshot_kind ?? ""}-${JSON.stringify(item.data)}`}`}
            onPendingAction={onPendingAction}
            pendingAction={pendingAction}
          />
        ))}
      </div>
    </article>
  );
}

function StructuredCard({
  item,
  onPendingAction,
  pendingAction,
}: {
  item: StructuredItem;
  onPendingAction: (id: string, action: "confirm" | "cancel") => void;
  pendingAction: PendingAction;
}) {
  const data = record(item.data);
  if (item.type === "financial_summary" && data) {
    return (
      <section className="assistant-data-card summary-result">
        <div className="assistant-data-card-heading"><span>Resumo financeiro</span>{stringValue(data.period_start) && stringValue(data.period_end) && <small>{displayDate(stringValue(data.period_start) ?? "")} – {displayDate(stringValue(data.period_end) ?? "")}</small>}</div>
        <div className="assistant-summary-values">
          <div><span>Receitas</span><strong>{formatCurrency(stringValue(data.income) ?? "0.00")}</strong></div>
          <div><span>Despesas</span><strong>{formatCurrency(stringValue(data.expenses) ?? "0.00")}</strong></div>
          <div><span>Resultado</span><strong>{formatCurrency(stringValue(data.result) ?? "0.00")}</strong></div>
        </div>
      </section>
    );
  }
  if (item.type === "monthly_forecast" && data && Array.isArray(data.items)) {
    const items = data.items.map((entry, index) => {
      const forecast = record(entry);
      if (!forecast) return null;
      const source = stringValue(forecast.source);
      const isIncome = stringValue(forecast.type) === "INCOME";
      const accountOrCard = stringValue(forecast.card_name) ?? stringValue(forecast.account_name);
      const description = stringValue(forecast.description) ?? "Compromisso";
      const dueDate = stringValue(forecast.due_date);
      const amount = stringValue(forecast.amount);
      const sourceLabel = source === "CARD_INVOICE" ? "Fatura" : isIncome ? "Receita prevista" : "Despesa prevista";
      return (
        <div className="assistant-transaction-row" key={stringValue(forecast.id) ?? index}>
          <span><strong>{description}</strong><small>{dueDate ? displayDate(dueDate) : ""} · {sourceLabel}{accountOrCard ? ` · ${accountOrCard}` : ""}</small></span>
          {amount && <b>{formatCurrency(amount)}</b>}
        </div>
      );
    });
    const periodStart = stringValue(data.period_start);
    const periodEnd = stringValue(data.period_end);
    return (
      <section className="assistant-data-card">
        <div className="assistant-data-card-heading"><span>Previsão do mês</span>{periodStart && periodEnd && <small>{displayDate(periodStart)} – {displayDate(periodEnd)}</small>}</div>
        <div className="assistant-summary-values assistant-month-forecast-values">
          <div><span>Despesas previstas</span><strong>{formatCurrency(stringValue(data.expenses) ?? "0.00")}</strong></div>
          <div><span>Receitas previstas</span><strong>{formatCurrency(stringValue(data.income) ?? "0.00")}</strong></div>
        </div>
        <div className="assistant-transaction-list">
          {items.length ? items : <p>Nenhuma conta ou fatura prevista para este mês.</p>}
        </div>
        {stringValue(data.unassigned_invoice_total) && stringValue(data.unassigned_invoice_total) !== "0.00" && <p className="forecast-unassigned-note">Faturas sem conta pagadora definida: {formatCurrency(stringValue(data.unassigned_invoice_total) ?? "0.00")}. Elas não reduzem o saldo projetado de uma conta.</p>}
      </section>
    );
  }
  if (item.type === "category_breakdown" && data && Array.isArray(data.categories)) {
    return (
      <section className="assistant-data-card">
        <div className="assistant-data-card-heading"><span>Despesas por categoria</span></div>
        <div className="assistant-category-list">
          {data.categories.map((entry, index) => {
            const category = record(entry);
            if (!category) return null;
            return <div key={stringValue(category.category_id) ?? index}><span>{stringValue(category.category_name) ?? "Categoria"}</span><strong>{formatCurrency(stringValue(category.amount) ?? "0.00")}</strong></div>;
          })}
          {data.categories.length === 0 && <p>Não há despesas neste período.</p>}
        </div>
      </section>
    );
  }
  if (item.type === "transaction_card" || item.type === "transfer_card") {
    const transactions = Array.isArray(item.data)
      ? item.data
      : Array.isArray(data?.items)
        ? data.items
        : data
          ? [data]
          : [];
    const summary = record(data?.summary);
    const income = stringValue(summary?.income_total);
    const expenses = stringValue(summary?.expenses_total);
    const transfers = stringValue(summary?.transfer_total);
    const cardPayments = stringValue(summary?.card_payment_total);
    const summaryCount = typeof summary?.transaction_count === "number"
      ? summary.transaction_count
      : null;
    const summaryMetrics = [
      ...(hasMoneyValue(income) ? [{ label: "Receitas", value: income }] : []),
      ...(hasMoneyValue(expenses)
        ? [{ label: "Despesas · inclui compras no cartão", value: expenses }]
        : []),
      ...(hasMoneyValue(transfers)
        ? [{ label: "Transferências · fora do resultado", value: transfers }]
        : []),
      ...(hasMoneyValue(cardPayments)
        ? [{ label: "Pagamentos de fatura · sem nova despesa", value: cardPayments }]
        : []),
      ...(hasMoneyValue(income) && hasMoneyValue(expenses) && stringValue(summary?.result_total)
        ? [{ label: "Resultado", value: stringValue(summary?.result_total) ?? "0.00" }]
        : []),
    ];
    const resultCount = summaryCount ?? transactions.length;
    const isSingleTransfer = item.type === "transfer_card" || (resultCount === 1 && stringValue(record(transactions[0])?.type) === "TRANSFER");
    return (
      <section className="assistant-data-card">
        <div className="assistant-data-card-heading"><span>{isSingleTransfer ? "Transferência" : resultCount === 1 ? "Lançamento" : "Lançamentos"}</span>{summaryCount !== null && <small>{summaryCount} {summaryCount === 1 ? "resultado" : "resultados"} no filtro</small>}</div>
        {summaryMetrics.length > 0 && <div className="assistant-transaction-summary">{summaryMetrics.map((metric) => <div key={metric.label}><span>{metric.label}</span><strong>{formatCurrency(metric.value)}</strong></div>)}</div>}
        <div className="assistant-transaction-list">
          {transactions.slice(0, 8).map((entry, index) => {
            const transaction = record(entry);
            if (!transaction) return null;
            const amount = stringValue(transaction.amount);
            const kind = stringValue(transaction.type);
            const kindLabel = kind === "TRANSFER" ? "Transferência entre contas" : kind === "CARD_PAYMENT" ? "Pagamento de fatura" : kind === "CARD_PURCHASE" ? "Compra no cartão" : kind === "INCOME" ? "Receita" : kind === "EXPENSE" ? "Despesa" : null;
            return (
              <div className="assistant-transaction-row" key={stringValue(transaction.id) ?? index}>
                <span><strong>{stringValue(transaction.description) ?? (kind === "TRANSFER" ? "Transferência entre contas" : "Movimento")}</strong><small>{kindLabel ? `${kindLabel} · ` : ""}{stringValue(transaction.occurred_at) ? displayDate(stringValue(transaction.occurred_at) ?? "") : ""}{stringValue(transaction.category_name) ? ` · ${stringValue(transaction.category_name)}` : ""}</small></span>
                {amount && <b>{formatCurrency(amount)}</b>}
              </div>
            );
          })}
          {transactions.length === 0 && <p>Nenhum lançamento encontrado.</p>}
        </div>
      </section>
    );
  }
  if (item.type === "account_card") {
    const accounts = Array.isArray(item.data) ? item.data : data ? [data] : [];
    const postMovement = item.snapshot_kind === "after_movement";
    return (
      <section className="assistant-data-card">
        <div className="assistant-data-card-heading"><span>{postMovement ? accounts.length === 1 ? "Saldo após esta movimentação" : "Saldos após esta movimentação" : accounts.length === 1 ? "Saldo da conta" : "Contas"}</span></div>
        <div className="assistant-transaction-list">
          {accounts.map((entry, index) => {
            const account = record(entry);
            if (!account) return null;
            const balance = stringValue(account.balance);
            return <div className="assistant-transaction-row" key={stringValue(account.id) ?? index}><span><strong>{stringValue(account.name) ?? "Conta"}</strong><small>{balance ? postMovement ? "Recalculado após o registro" : "Saldo consultado nesta resposta" : "Saldo inicial não informado"}</small></span><b>{balance ? formatCurrency(balance) : "Pendente"}</b></div>;
          })}
        </div>
      </section>
    );
  }
  if (item.type === "card_summary") {
    const cards = Array.isArray(item.data) ? item.data : data ? [data] : [];
    return (
      <section className="assistant-data-card">
        <div className="assistant-data-card-heading"><span>{cards.length === 1 ? "Cartão" : "Cartões"}</span></div>
        <div className="assistant-transaction-list">
          {cards.map((entry, index) => {
            const card = record(entry);
            if (!card) return null;
            return <div className="assistant-transaction-row" key={stringValue(card.id) ?? index}><span><strong>{stringValue(card.name) ?? "Cartão"}</strong><small>{stringValue(card.available_limit) ? `Disponível ${formatCurrency(stringValue(card.available_limit) ?? "0.00")}` : "Limite utilizado"}{typeof card.closing_day === "number" ? ` · fecha dia ${card.closing_day}` : ""}{typeof card.due_day === "number" ? ` · vence dia ${card.due_day}` : ""}</small></span><b>{formatCurrency(stringValue(card.used_limit) ?? "0.00")}</b></div>;
          })}
          {cards.length === 0 && <p>Nenhum cartão cadastrado.</p>}
        </div>
      </section>
    );
  }
  if (item.type === "invoice_summary" && data) {
    if (data.found === false) {
      return <section className="assistant-data-card"><div className="assistant-data-card-heading"><span>Fatura</span>{stringValue(data.credit_card_name) && <small>{stringValue(data.credit_card_name)}</small>}</div><p className="assistant-card-note">Ainda não há fatura registrada para este cartão.</p></section>;
    }
    return (
      <section className="assistant-data-card">
        <div className="assistant-data-card-heading"><span>Fatura</span>{stringValue(data.credit_card_name) && <small>{stringValue(data.credit_card_name)}{stringValue(data.status) ? ` · ${invoiceStatusLabel(stringValue(data.status) ?? "")}` : ""}</small>}</div>
        <div className="assistant-summary-values">
          <div><span>Total</span><strong>{formatCurrency(stringValue(data.total) ?? "0.00")}</strong></div>
          <div><span>Em aberto</span><strong>{formatCurrency(stringValue(data.outstanding) ?? "0.00")}</strong></div>
          <div><span>Vencimento</span><strong>{stringValue(data.due_date) ? displayDate(stringValue(data.due_date) ?? "") : "—"}</strong></div>
        </div>
        {stringValue(data.closing_date) && <p className="assistant-card-note">Fechamento {displayDate(stringValue(data.closing_date) ?? "")}</p>}
      </section>
    );
  }
  if (item.type === "confirmation" && data) {
    const changes = record(data.changes);
    const pending = item.status === "pending" && Boolean(item.tool_call_id);
    return (
      <section className="assistant-data-card assistant-confirmation">
        <div className="assistant-data-card-heading"><span>{stringValue(data.title) ?? "Confirme a alteração"}</span><small>Revisão necessária</small></div>
        {changes && <ul>{Object.entries(changes).map(([key, value]) => <li key={key}><span>{fieldLabel(key)}</span><strong>{String(value ?? "—")}</strong></li>)}</ul>}
        {stringValue(data.message) && <p className="assistant-card-note">{stringValue(data.message)}</p>}
        {pending && <div className="assistant-confirm-actions"><button className="assistant-confirm-button" disabled={pendingAction?.id === item.tool_call_id} onClick={() => onPendingAction(item.tool_call_id ?? "", "confirm")} type="button">{pendingAction?.id === item.tool_call_id && pendingAction?.action === "confirm" ? "Aplicando…" : "Confirmar"}</button><button className="assistant-cancel-button" disabled={pendingAction?.id === item.tool_call_id} onClick={() => onPendingAction(item.tool_call_id ?? "", "cancel")} type="button">Cancelar</button></div>}
      </section>
    );
  }
  if (item.type === "error" && data) {
    return <div className="assistant-inline-error"><strong>Não concluído</strong><span>{stringValue(data.message) ?? "Não foi possível concluir a operação."}</span></div>;
  }
  if (item.type === "success") {
    const createdCategory = data?.type === "INCOME" || data?.type === "EXPENSE"
      ? stringValue(data.name)
      : null;
    const title = stringValue(data?.title) ?? (createdCategory ? "Categoria criada" : "Concluído");
    const message = stringValue(data?.message)
      ?? (createdCategory ? `A categoria “${createdCategory}” foi criada.` : "A operação foi concluída.");
    return <div className="assistant-inline-success"><strong>{title}</strong><span>{message}</span></div>;
  }
  return null;
}

function invoiceStatusLabel(value: string): string {
  const labels: Record<string, string> = { OPEN: "Aberta", CLOSED: "Fechada", PARTIALLY_PAID: "Parcialmente paga", PAID: "Paga", OVERDUE: "Atrasada" };
  return labels[value] ?? value;
}

function fieldLabel(value: string): string {
  const labels: Record<string, string> = {
    transaction_id: "Lançamento",
    description: "Descrição",
    amount: "Valor",
    occurred_at: "Data",
    account_id: "Conta",
    category_id: "Categoria",
    movement_type: "Tipo",
  };
  return labels[value] ?? value;
}

type ContextMode = "overview" | "spending" | "account" | "card";

function normalizeForMatch(message: string): string {
  return message
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function contextMode(message: string, cards: ContextCard[], accounts: ContextAccount[]): ContextMode {
  const normalized = normalizeForMatch(message);
  const namesCard = cards.some((card) => normalized.includes(normalizeForMatch(card.name)));
  if (namesCard || /(fatura|cartao|limite)/.test(normalized)) return "card";
  const namesAccount = accounts.some((account) => normalized.includes(normalizeForMatch(account.name)));
  if (namesAccount || /\bconta\b|\bextrato\b|saldo da conta|movimenta(?:cao|coes) da conta/.test(normalized)) return "account";
  if (/(gasto|gastei|despesa|categoria|aliment|mercado|combustivel|mes|periodo)/.test(normalized)) return "spending";
  if (cards.some((card) => card.institution && normalized.includes(normalizeForMatch(card.institution)))) return "card";
  return "overview";
}

function todayInSaoPaulo(): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "America/Sao_Paulo",
    year: "numeric",
  }).formatToParts(new Date());
  const part = (type: "year" | "month" | "day") => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function contextInvoiceToShow(invoices: ContextInvoice[], today: string): ContextInvoice | null {
  const openInvoices = invoices.filter((invoice) => invoice.outstanding !== "0.00");
  const overdueInvoice = openInvoices
    .filter((invoice) => invoice.due_date < today)
    .sort((left, right) => right.due_date.localeCompare(left.due_date))[0];
  if (overdueInvoice) return overdueInvoice;

  const upcomingInvoice = openInvoices
    .filter((invoice) => invoice.due_date >= today)
    .sort((left, right) => left.due_date.localeCompare(right.due_date))[0];
  if (upcomingInvoice) return upcomingInvoice;

  return [...invoices].sort((left, right) => right.due_date.localeCompare(left.due_date))[0] ?? null;
}

function ContextPanel({
  dashboard,
  latestUserMessage,
  accounts,
  cards,
  mobileOpen,
  onClose,
}: {
  dashboard: Dashboard | null;
  latestUserMessage: string;
  accounts: ContextAccount[];
  cards: ContextCard[];
  mobileOpen: boolean;
  onClose: () => void;
}) {
  const mode = contextMode(latestUserMessage, cards, accounts);
  const normalizedMessage = normalizeForMatch(latestUserMessage);
  const selectedCard = cards.find((card) => normalizedMessage.includes(normalizeForMatch(card.name)) || (card.institution && normalizedMessage.includes(normalizeForMatch(card.institution)))) ?? (cards.length === 1 ? cards[0] : null);
  const selectedCardId = selectedCard?.id ?? null;
  const selectedAccount = accounts.find((account) => normalizedMessage.includes(normalizeForMatch(account.name))) ?? (accounts.length === 1 ? accounts[0] : null);
  const today = todayInSaoPaulo();
  const [invoice, setInvoice] = useState<ContextInvoice | null>(null);
  const [invoiceLoading, setInvoiceLoading] = useState(false);
  const [previousDashboard, setPreviousDashboard] = useState<Dashboard | null>(null);
  const [previousDashboardLoading, setPreviousDashboardLoading] = useState(false);
  const previousMonthRequested = /(mes passado|mes anterior|ultimo mes)/.test(normalizedMessage);
  const previousMonth = dashboard ? previousMonthQuery(dashboard.period_start) : null;
  useEffect(() => {
    if (mode !== "card" || !selectedCardId) {
      setInvoice(null);
      setInvoiceLoading(false);
      return;
    }
    let active = true;
    setInvoice(null);
    setInvoiceLoading(true);
    apiRequest<ContextInvoice[]>(`/api/cards/${selectedCardId}/invoices`)
      .then((rows) => { if (active) setInvoice(contextInvoiceToShow(rows, todayInSaoPaulo())); })
      .catch(() => { if (active) setInvoice(null); })
      .finally(() => { if (active) setInvoiceLoading(false); });
    return () => { active = false; };
  }, [mode, selectedCardId]);

  useEffect(() => {
    if (mode !== "spending" || !previousMonth) {
      setPreviousDashboard(null);
      setPreviousDashboardLoading(false);
      return;
    }
    let active = true;
    setPreviousDashboardLoading(true);
    apiRequest<Dashboard>(`/api/dashboard/summary?${previousMonth}`)
      .then((summary) => { if (active) setPreviousDashboard(summary); })
      .catch(() => { if (active) setPreviousDashboard(null); })
      .finally(() => { if (active) setPreviousDashboardLoading(false); });
    return () => { active = false; };
  }, [mode, previousMonth]);

  const invoiceHeading = !invoice
    ? "Fatura do cartão"
    : invoice.outstanding === "0.00"
      ? "Última fatura registrada"
      : invoice.due_date < today
        ? "Fatura em atraso"
        : "Próxima fatura em aberto";

  const contextCopy = {
    overview: { title: "Resumo", detail: "Sua posição financeira", icon: WalletCards },
    spending: { title: "Gastos do período", detail: previousMonthRequested ? "Mês passado e atual" : "Este mês e o anterior", icon: ChartNoAxesCombined },
    account: { title: selectedAccount?.name ?? "Contas", detail: "Saldo e movimentações", icon: Landmark },
    card: { title: selectedCard?.name ?? "Cartões", detail: "Fatura, limite e datas", icon: CreditCard },
  }[mode];
  const ContextIcon = contextCopy.icon;
  const spendingDashboard = previousMonthRequested ? previousDashboard : dashboard;
  const recentExpenses = spendingDashboard?.recent_transactions.filter((transaction) =>
    transaction.type === "EXPENSE" || transaction.type === "CARD_PURCHASE",
  ) ?? [];
  const accountMovements = dashboard?.recent_transactions.filter((transaction) =>
    selectedAccount && (
      transaction.account_id === selectedAccount.id ||
      transaction.source_account_id === selectedAccount.id ||
      transaction.destination_account_id === selectedAccount.id
    ),
  ) ?? [];

  return (
    <aside className={mobileOpen ? "assistant-context-panel mobile-open" : "assistant-context-panel"} data-focus={mode} aria-label="Contexto financeiro">
      <div className="context-panel-title">
        <span className="context-icon" aria-hidden="true"><ContextIcon size={18} strokeWidth={1.8} /></span>
        <div><strong>{contextCopy.title}</strong><small>{contextCopy.detail}</small></div>
        <button aria-label="Fechar contexto" className="context-close" onClick={onClose} type="button"><X aria-hidden="true" size={18} /></button>
      </div>
      {!dashboard ? <p className="context-empty">Resumo financeiro indisponível no momento.</p> : mode === "card" ? (
        selectedCard ? <>
          <section className="context-balance"><span>Limite disponível</span><strong>{formatCurrency(selectedCard.available_limit)}</strong><small>Em uso {formatCurrency(selectedCard.used_limit)} de {formatCurrency(selectedCard.credit_limit)}</small></section>
          <div className="context-metrics context-dates">
            <div><span>Fechamento</span><strong>Dia {selectedCard.closing_day}</strong></div>
            <div><span>Vencimento</span><strong>{selectedCard.next_due_date ? displayDate(selectedCard.next_due_date) : `Dia ${selectedCard.due_day}`}</strong></div>
          </div>
          <section className="context-cards">
            <div className="context-section-heading"><span>{invoiceHeading}</span>{invoice && <span>{invoiceStatusLabel(invoice.status)}</span>}</div>
            {invoiceLoading ? <p>Carregando fatura…</p> : invoice ? <div className="context-metrics">
              <div><span>Total</span><strong>{formatCurrency(invoice.total)}</strong></div>
              <div><span>Em aberto</span><strong>{formatCurrency(invoice.outstanding)}</strong></div>
              <div><span>Vencimento</span><strong>{displayDate(invoice.due_date)}</strong></div>
            </div> : <p>{selectedCard.next_due_date ? `Próximo vencimento ${displayDate(selectedCard.next_due_date)}.` : "Ainda não há fatura registrada para este cartão."}</p>}
          </section>
        </> : cards.length ? <section className="context-cards"><div className="context-section-heading"><span>Seus cartões</span></div>{cards.slice(0, 4).map((card) => <div className="context-card-row" key={card.id}><span>{card.name}<small>{card.institution ?? "Cartão"} · disponível {formatCurrency(card.available_limit)}</small><small>Fecha dia {card.closing_day} · vence dia {card.due_day}</small></span><strong>{formatCurrency(card.used_limit)}</strong></div>)}</section> : <p className="context-empty">Nenhum cartão cadastrado.</p>
      ) : mode === "account" ? (
        selectedAccount ? <>
          <section className="context-balance"><span>Saldo da conta</span><strong>{selectedAccount.balance === null ? "Pendente" : formatCurrency(selectedAccount.balance)}</strong><small>{selectedAccount.balance === null ? "Informe o saldo inicial e a data-base" : selectedAccount.name}</small></section>
          <section className="context-cards context-recent-list">
            <div className="context-section-heading"><span>Movimentações recentes</span><span>{Math.min(accountMovements.length, 4)}</span></div>
            {accountMovements.length ? accountMovements.slice(0, 4).map((transaction) => <ContextMovementRow key={transaction.id} transaction={transaction} />) : <p>Sem movimentações recentes nesta conta.</p>}
          </section>
        </> : accounts.length ? <section className="context-cards"><div className="context-section-heading"><span>Saldos das contas</span></div>{accounts.slice(0, 4).map((account) => <div className="context-card-row" key={account.id}><span>{account.name}</span><strong>{account.balance === null ? "Pendente" : formatCurrency(account.balance)}</strong></div>)}</section> : <p className="context-empty">Nenhuma conta cadastrada.</p>
      ) : mode === "spending" ? <>
        <section className="context-balance"><span>Saldo em contas correntes</span><strong>{dashboard.checking_balance === null ? (dashboard.incomplete_checking_account_count ? "Incompleto" : "Não cadastrado") : formatCurrency(dashboard.checking_balance)}</strong><small>{dashboard.checking_balance === null ? `${dashboard.incomplete_checking_account_count} conta(s) corrente(s) precisam de saldo inicial e data-base` : "Poupança e outros tipos aparecem separados"}</small></section>
        <ForecastContext dashboard={dashboard} />
        {previousMonthRequested && !previousDashboard ? <p className="context-empty">{previousDashboardLoading ? "Carregando o mês passado…" : "Resumo do mês passado indisponível."}</p> : <>
        <div className="context-metrics context-period-comparison">
          <div><span>{previousMonthRequested ? displayMonth(spendingDashboard?.period_start ?? "") : displayMonth(dashboard.period_start)}</span><strong>{formatCurrency(spendingDashboard?.monthly_expenses ?? "0.00")}</strong></div>
          <div><span>{previousMonthRequested ? displayMonth(dashboard.period_start) : previousDashboard ? displayMonth(previousDashboard.period_start) : "Mês anterior"}</span><strong>{formatCurrency(previousMonthRequested ? dashboard.monthly_expenses : previousDashboard?.monthly_expenses ?? "0.00")}</strong></div>
        </div>
        <section className="context-cards context-categories">
          <div className="context-section-heading"><span>Por categoria</span><span>{displayMonth(spendingDashboard?.period_start ?? dashboard.period_start)}</span></div>
          {spendingDashboard?.expenses_by_category.length ? spendingDashboard.expenses_by_category.slice(0, 5).map((category) => <div className="context-category-row" key={category.category_id}><span>{category.category_name}</span><strong>{formatCurrency(category.amount)}</strong></div>) : <p>Nenhuma despesa categorizada neste período.</p>}
        </section>
        {recentExpenses.length > 0 && <section className="context-cards context-recent-list"><div className="context-section-heading"><span>Despesas recentes</span></div>{recentExpenses.slice(0, 3).map((transaction) => <ContextMovementRow key={transaction.id} transaction={transaction} />)}</section>}
        </>}
      </> : <>
        <section className="context-balance"><span>Saldo em contas correntes</span><strong>{dashboard.checking_balance === null ? (dashboard.incomplete_checking_account_count > 0 ? "Incompleto" : "Não cadastrado") : formatCurrency(dashboard.checking_balance)}</strong><small>{dashboard.checking_balance === null ? `${dashboard.incomplete_checking_account_count} conta(s) corrente(s) precisam de saldo inicial e data-base` : "Somente contas correntes"}</small></section>
        <div className="context-metrics context-overview-metrics">
          <div><span>Gastos em {displayMonth(dashboard.period_start)}</span><strong>{formatCurrency(dashboard.monthly_expenses)}</strong></div>
          <div><span>Contas acompanhadas</span><strong>{accounts.length}</strong></div>
        </div>
        {dashboard.account_type_balances.filter((group) => group.account_type !== "CHECKING").length > 0 && <section className="context-cards"><div className="context-section-heading"><span>Outros saldos, separados</span></div>{dashboard.account_type_balances.filter((group) => group.account_type !== "CHECKING").map((group) => <div className="context-card-row" key={group.account_type}><span>{accountTypeLabel(group.account_type)}<small>Saldo real · projeção {group.projected_balance === null ? "indisponível" : formatCurrency(group.projected_balance)}</small></span><strong>{group.balance === null ? "Pendente" : formatCurrency(group.balance)}</strong></div>)}</section>}
        {accounts.length > 0 && <section className="context-cards"><div className="context-section-heading"><span>Saldos por conta</span></div>{accounts.slice(0, 4).map((account) => <div className="context-card-row" key={account.id}><span>{account.name}<small>{accountTypeLabel(account.type)}</small></span><strong>{account.balance === null ? "Pendente" : formatCurrency(account.balance)}</strong></div>)}</section>}
        <ForecastContext dashboard={dashboard} />
        {dashboard.recent_transactions.length > 0 && <section className="context-cards context-recent-list"><div className="context-section-heading"><span>Últimos movimentos</span></div>{dashboard.recent_transactions.slice(0, 3).map((transaction) => <ContextMovementRow key={transaction.id} transaction={transaction} />)}</section>}
      </>}
      {dashboard && <p className="context-truth-note"><span aria-hidden="true">✓</span> Valores do Finance Engine</p>}
    </aside>
  );
}

function ContextMovementRow({ transaction }: { transaction: Dashboard["recent_transactions"][number] }) {
  const isIncome = transaction.type === "INCOME";
  const isTransfer = transaction.type === "TRANSFER";
  const isExpense = transaction.type === "EXPENSE" || transaction.type === "CARD_PURCHASE";
  const MovementIcon = isIncome ? ArrowDownLeft : isTransfer ? ArrowLeftRight : ArrowUpRight;
  const label = isTransfer ? "Transferência" : transaction.type === "CARD_PAYMENT" ? "Pagamento de fatura" : transaction.category_name ?? (isIncome ? "Receita" : "Despesa");
  const tone = isIncome ? "income" : isExpense ? "expense" : "transfer";
  const prefix = isIncome ? "+" : isTransfer ? "" : "−";
  return <div className="context-transaction-row" key={transaction.id}>
    <span className={`context-transaction-icon ${tone}`} aria-hidden="true"><MovementIcon size={15} strokeWidth={1.9} /></span>
    <span className="context-transaction-copy"><strong>{transaction.description}</strong><small>{label} · {displayDate(transaction.occurred_at)}</small></span>
    <strong className={`context-transaction-amount ${tone}`}>{prefix}{formatCurrency(transaction.amount)}</strong>
  </div>;
}

function ForecastContext({ dashboard }: { dashboard: Dashboard }) {
  const checkingProjection = dashboard.account_type_balances.find((group) => group.account_type === "CHECKING")?.projected_balance;
  const expenses = dashboard.forecast_items.filter((item) => item.type === "EXPENSE").slice(0, 5);
  return (
    <section className="context-cards context-forecast">
      <div className="context-section-heading"><span>A pagar até {displayDate(dashboard.forecast_end)}</span></div>
      <div className="context-metrics">
        <div><span>Total previsto</span><strong>{formatCurrency(dashboard.forecast_payables_total)}</strong></div>
        <div><span>Em atraso</span><strong>{formatCurrency(dashboard.forecast_overdue_total)}</strong></div>
        <div><span>Próximos 7 dias</span><strong>{formatCurrency(dashboard.forecast_next_7_days_total)}</strong></div>
        <div><span>Saldo corrente projetado</span><strong>{checkingProjection == null ? "Indisponível" : formatCurrency(checkingProjection)}</strong></div>
      </div>
      {dashboard.forecast_unassigned_invoice_total !== "0.00" && <p className="forecast-unassigned-note">Faturas sem conta pagadora: {formatCurrency(dashboard.forecast_unassigned_invoice_total)}.</p>}
      {expenses.length ? expenses.map((item) => <div className="context-card-row" key={item.id}><span>{item.description}<small>{displayDate(item.due_date)} · {item.status === "OVERDUE" ? "Em atraso" : item.status === "DUE_SOON" ? "Próximos 7 dias" : "Neste mês"}</small></span><strong>{formatCurrency(item.amount)}</strong></div>) : <p>Nenhum pagamento previsto até {displayDate(dashboard.forecast_end)}.</p>}
    </section>
  );
}

function SettingsView({
  loading,
  email,
  status,
  usage,
  diagnostics,
  memories,
  accounts,
  cards,
  theme,
  onThemeChange,
  onSaveMemory,
  onDeleteMemory,
}: {
  loading: boolean;
  email: string;
  status: AIStatus | null;
  usage: Usage | null;
  diagnostics: AIDiagnostic[];
  memories: Memory[];
  accounts: ContextAccount[];
  cards: ContextCard[];
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
  onSaveMemory: (content: string, id: string | null) => Promise<void>;
  onDeleteMemory: (id: string) => void;
}) {
  const assistantPreferenceRecord = memories.find((memory) => memory.content.startsWith(ASSISTANT_PREFERENCES_PREFIX));
  const assistantPreferenceContent = assistantPreferenceRecord?.content;
  const visibleMemories = memories.filter((memory) => !memory.content.startsWith(ASSISTANT_PREFERENCES_PREFIX));
  const memoryPagination = usePagination(visibleMemories, String(visibleMemories.length));
  const diagnosticsPagination = usePagination(diagnostics, String(diagnostics.length));
  const [assistantPreferences, setAssistantPreferences] = useState(DEFAULT_ASSISTANT_PREFERENCES);
  const [savingAssistantPreferences, setSavingAssistantPreferences] = useState(false);
  const [assistantPreferencesError, setAssistantPreferencesError] = useState("");
  const [assistantPreferencesSaved, setAssistantPreferencesSaved] = useState(false);
  const [memoryDraft, setMemoryDraft] = useState("");
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const { editorRef: memoryEditorRef, scrollToEditor: scrollToMemoryEditor } = useEditorScroll<HTMLFormElement>();
  const [savingMemory, setSavingMemory] = useState(false);
  const [memoryError, setMemoryError] = useState("");
  const [managedUsers, setManagedUsers] = useState<ManagedUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [usersError, setUsersError] = useState("");
  const [userNameDraft, setUserNameDraft] = useState("");
  const [userEmailDraft, setUserEmailDraft] = useState("");
  const [userPasswordDraft, setUserPasswordDraft] = useState("");
  const [creatingUser, setCreatingUser] = useState(false);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);
  const [confirmingDeleteUserId, setConfirmingDeleteUserId] = useState<string | null>(null);
  const [resettingMfaUserId, setResettingMfaUserId] = useState<string | null>(null);
  const [resetMfaPassword, setResetMfaPassword] = useState("");
  const [resetMfaTotp, setResetMfaTotp] = useState("");
  const [resettingMfa, setResettingMfa] = useState(false);
  const [usersNotice, setUsersNotice] = useState("");
  const ownerCanManageUsers = email.trim().toLocaleLowerCase("en-US") === "gamercreeper74@gmail.com";
  const managedUsersPagination = usePagination(managedUsers, String(managedUsers.length));

  useEffect(() => {
    if (!ownerCanManageUsers) return;
    let active = true;
    setUsersLoading(true);
    apiRequest<ManagedUser[]>("/api/admin/users")
      .then((rows) => { if (active) setManagedUsers(rows); })
      .catch((error: unknown) => {
        if (active) setUsersError(error instanceof Error ? error.message : "Não foi possível carregar as contas.");
      })
      .finally(() => { if (active) setUsersLoading(false); });
    return () => { active = false; };
  }, [ownerCanManageUsers]);

  async function createManagedUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreatingUser(true);
    setUsersError("");
    setUsersNotice("");
    try {
      const created = await apiRequest<ManagedUser>("/api/admin/users", {
        method: "POST",
        body: JSON.stringify({ email: userEmailDraft, display_name: userNameDraft, password: userPasswordDraft }),
      });
      setManagedUsers((current) => [created, ...current.filter((managedUser) => managedUser.id !== created.id)]);
      setUsersNotice(`Conta de ${created.display_name} criada. No primeiro acesso, a pessoa deverá configurar um autenticador individual.`);
      setUserNameDraft("");
      setUserEmailDraft("");
      setUserPasswordDraft("");
    } catch (error) {
      setUsersError(error instanceof Error ? error.message : "Não foi possível criar a conta.");
    } finally {
      setCreatingUser(false);
    }
  }

  async function deleteManagedUser(managedUser: ManagedUser) {
    setDeletingUserId(managedUser.id);
    setUsersError("");
    setUsersNotice("");
    try {
      await apiRequest<void>(`/api/admin/users/${managedUser.id}`, { method: "DELETE" });
      setManagedUsers((current) => current.filter((user) => user.id !== managedUser.id));
      setConfirmingDeleteUserId(null);
      setUsersNotice(`O acesso de ${managedUser.display_name} foi excluído.`);
    } catch (error) {
      setUsersError(error instanceof Error ? error.message : "Não foi possível excluir o acesso.");
    } finally {
      setDeletingUserId(null);
    }
  }

  async function resetManagedUserMfa(event: FormEvent<HTMLFormElement>, managedUser: ManagedUser) {
    event.preventDefault();
    setResettingMfa(true);
    setUsersError("");
    setUsersNotice("");
    try {
      await apiRequest<void>(`/api/admin/users/${managedUser.id}/mfa/reset`, {
        method: "POST",
        body: JSON.stringify({ current_password: resetMfaPassword, totp_code: resetMfaTotp }),
      });
      setManagedUsers((current) => current.map((user) => user.id === managedUser.id ? { ...user, mfa_enrolled: false } : user));
      setResettingMfaUserId(null);
      setResetMfaPassword("");
      setResetMfaTotp("");
      setUsersNotice(`O autenticador de ${managedUser.display_name} foi redefinido e as sessões existentes foram encerradas. No próximo acesso, a pessoa deverá parear um novo autenticador.`);
    } catch (error) {
      setUsersError(error instanceof Error ? error.message : "Não foi possível redefinir o autenticador.");
    } finally {
      setResettingMfa(false);
      setResetMfaTotp("");
    }
  }
  useEffect(() => {
    const saved = parseAssistantPreferences(assistantPreferenceContent);
    const activeAccounts = accounts.filter((account) => account.is_active);
    const activeCards = cards.filter((card) => card.is_active);
    setAssistantPreferences({
      ...saved,
      defaultAccount: saved.defaultAccount || (activeAccounts.length === 1 ? activeAccounts[0].name : ""),
      mainCard: saved.mainCard || (activeCards.length === 1 ? activeCards[0].name : ""),
    });
  }, [assistantPreferenceContent, accounts, cards]);

  function updateAssistantPreference<Key extends keyof AssistantPreferences>(key: Key, value: AssistantPreferences[Key]) {
    setAssistantPreferences((current) => ({ ...current, [key]: value }));
    setAssistantPreferencesSaved(false);
    setAssistantPreferencesError("");
  }

  async function saveAssistantPreferences() {
    setSavingAssistantPreferences(true);
    setAssistantPreferencesError("");
    setAssistantPreferencesSaved(false);
    try {
      await onSaveMemory(`${ASSISTANT_PREFERENCES_PREFIX}${JSON.stringify(assistantPreferences)}`, assistantPreferenceRecord?.id ?? null);
      setAssistantPreferencesSaved(true);
    } catch (saveError) {
      setAssistantPreferencesError(saveError instanceof Error ? saveError.message : "Não foi possível salvar as preferências.");
    } finally {
      setSavingAssistantPreferences(false);
    }
  }

  async function submitMemory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = memoryDraft.trim();
    if (!content) return;
    setSavingMemory(true);
    setMemoryError("");
    try {
      await onSaveMemory(content, editingMemoryId);
      setMemoryDraft("");
      setEditingMemoryId(null);
    } catch (saveError) {
      setMemoryError(saveError instanceof Error ? saveError.message : "Não foi possível salvar a preferência.");
    } finally {
      setSavingMemory(false);
    }
  }

  function editMemory(memory: Memory) {
    setMemoryDraft(memory.content);
    setEditingMemoryId(memory.id);
    setMemoryError("");
    scrollToMemoryEditor();
  }

  function chooseMemoryExample(content: string) {
    setMemoryDraft(content);
    setEditingMemoryId(null);
    setMemoryError("");
  }

  return (
    <section className="assistant-settings-page">
      <div className="assistant-settings-heading"><p className="assistant-eyebrow">Seu jeito de usar</p><h1>Preferências da SophIA</h1><p>Como a SophIA trabalha com você. Suas preferências não alteram lançamentos.</p></div>
      {loading ? <div className="assistant-settings-loading">Carregando…</div> : (
        <div className="assistant-settings-grid">
          <section className="assistant-settings-card">
            <h2>SophIA</h2>
            <div className="settings-row"><span>Provedor</span><strong>{status?.provider === "ollama" ? "Ollama · local" : status?.provider === "chatgpt_plan" ? "ChatGPT · plano Plus" : "—"}</strong></div>
            <div className="settings-row"><span>Conexão</span><strong className={status?.configured ? "settings-state ready" : "settings-state"}>{status?.configured ? status?.provider === "ollama" ? "Ativa na VM" : "Conta autorizada" : status ? "Aguardando conexão" : "Verificando"}</strong></div>
            <div className="settings-row"><span>Modelo rápido</span><strong>{status?.fast_model ?? "—"}</strong></div>
            <div className="settings-row"><span>Modelo avançado</span><strong>{status?.smart_model ?? "—"}</strong></div>
            {status && !status.configured && <p className="settings-help">{status.provider === "ollama" ? "O serviço ou o modelo local não está disponível. A conversa será retomada quando o modelo estiver pronto na VM." : "Conecte sua conta ChatGPT pelo procedimento seguro descrito no README. Sem essa autorização, a conversa fica pausada."} Contas, lançamentos, cartões e as demais áreas financeiras continuam disponíveis.</p>}
          </section>
          {ownerCanManageUsers && <section className="assistant-settings-card settings-managed-users">
            <h2>Contas de acesso</h2>
            <p>Crie contas de login para outras pessoas. Esta área e a API são restritas ao proprietário; cada pessoa mantém seus próprios dados financeiros. Todas as contas exigem autenticador individual. A pessoa configura o MFA no primeiro acesso usando a senha inicial definida aqui.</p>
            <form className="settings-managed-user-form" onSubmit={(event) => void createManagedUser(event)}>
              <label>Nome da pessoa<input autoComplete="name" maxLength={100} onChange={(event) => setUserNameDraft(event.target.value)} required value={userNameDraft} /></label>
              <label>E-mail de acesso<input autoComplete="email" maxLength={320} onChange={(event) => setUserEmailDraft(event.target.value)} required type="email" value={userEmailDraft} /></label>
              <label>Senha inicial<input autoComplete="new-password" minLength={12} maxLength={128} onChange={(event) => setUserPasswordDraft(event.target.value)} required type="password" value={userPasswordDraft} /><small>Use pelo menos 12 caracteres e envie à pessoa por um canal privado.</small></label>
              <button className="settings-memory-save" disabled={creatingUser || userPasswordDraft.length < 12} type="submit">{creatingUser ? "Criando conta…" : "Criar conta"}</button>
            </form>
            {usersError && <p className="settings-form-error" role="alert">{usersError}</p>}
            {usersNotice && <p aria-live="polite" className="settings-user-notice" role="status">{usersNotice}</p>}
            <div className="settings-memory-list-heading"><strong>Contas cadastradas</strong><span>{managedUsers.length}</span></div>
            {usersLoading ? <p className="settings-help">Carregando contas…</p> : managedUsers.length === 0 ? <p className="settings-help">Nenhuma conta adicional cadastrada.</p> : <div className="settings-managed-user-list">
              {managedUsersPagination.items.map((managedUser) => {
                const isOwner = managedUser.email.trim().toLocaleLowerCase("en-US") === "gamercreeper74@gmail.com";
                return <div className="settings-managed-user-row" key={managedUser.id}>
                  <span><strong>{managedUser.display_name}</strong><small>{managedUser.email}</small><small>Criada em {new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" }).format(new Date(managedUser.created_at))}</small>{!isOwner && <small className={managedUser.mfa_enrolled ? "settings-state ready" : "settings-state"}>{managedUser.mfa_enrolled ? "Autenticador configurado" : "Autenticador pendente"}</small>}</span>
                  {!isOwner && <div className={`settings-managed-user-actions${resettingMfaUserId === managedUser.id ? " settings-reset-open" : ""}`}>
                    {managedUser.mfa_enrolled && (resettingMfaUserId === managedUser.id ? <form className="settings-managed-user-reset" onSubmit={(event) => void resetManagedUserMfa(event, managedUser)}>
                      <p>Confirme sua senha e o código MFA atual. Isso encerrará todas as sessões de {managedUser.display_name} e exigirá um novo pareamento.</p>
                      <label>Sua senha<input autoComplete="current-password" minLength={12} name="current_password" onChange={(event) => setResetMfaPassword(event.target.value)} required type="password" value={resetMfaPassword} /></label>
                      <label>Seu código MFA<input autoComplete="one-time-code" inputMode="numeric" maxLength={6} minLength={6} name="totp_code" onChange={(event) => setResetMfaTotp(event.target.value.replace(/\D/g, "").slice(0, 6))} pattern="[0-9]{6}" required value={resetMfaTotp} /></label>
                      <button disabled={resettingMfa || resetMfaPassword.length < 12 || resetMfaTotp.length !== 6} type="submit">{resettingMfa ? "Redefinindo…" : "Confirmar redefinição"}</button>
                      <button disabled={resettingMfa} onClick={() => { setResettingMfaUserId(null); setResetMfaPassword(""); setResetMfaTotp(""); }} type="button">Cancelar</button>
                    </form> : <button onClick={() => { setUsersError(""); setResettingMfaUserId(managedUser.id); }} type="button">Redefinir MFA</button>)}
                    {confirmingDeleteUserId === managedUser.id ? <>
                      <span>Excluir o acesso e encerrar as sessões desta pessoa?</span>
                      <button disabled={deletingUserId === managedUser.id} onClick={() => void deleteManagedUser(managedUser)} type="button">{deletingUserId === managedUser.id ? "Excluindo…" : `Confirmar exclusão de ${managedUser.display_name}`}</button>
                      <button disabled={deletingUserId === managedUser.id} onClick={() => setConfirmingDeleteUserId(null)} type="button">Cancelar</button>
                    </> : <button aria-label={`Excluir acesso de ${managedUser.display_name}`} onClick={() => { setUsersError(""); setConfirmingDeleteUserId(managedUser.id); }} type="button">Excluir acesso</button>}
                  </div>}
                </div>;
              })}
              <PaginationControls end={managedUsersPagination.end} label="Paginação das contas de acesso" onPageChange={managedUsersPagination.setPage} page={managedUsersPagination.page} pageCount={managedUsersPagination.pageCount} start={managedUsersPagination.start} total={managedUsersPagination.total} />
            </div>}
            <p className="settings-help">Para preservar os registros, a API bloqueia a exclusão quando a conta tem dados financeiros ou pessoais associados.</p>
          </section>}
          <section className="assistant-settings-card">
            <h2>Uso da SophIA</h2>
            <p className="settings-period-label">Hoje</p>
            <div className="settings-usage-grid"><div><strong>{usage?.calls_today ?? 0}</strong><span>respostas</span></div><div><strong>{usage?.input_tokens_today ?? 0}</strong><span>tokens de entrada</span></div><div><strong>{usage?.output_tokens_today ?? 0}</strong><span>tokens de saída</span></div></div>
            <div className="settings-cost-row"><span>Custo estimado</span><strong>{status?.provider === "ollama" ? "Sem cobrança por tokens" : status?.provider === "chatgpt_plan" ? "Incluído no Plus" : formatUsdCost(usage?.cost_usd_today)}</strong></div>
            <p className="settings-period-label">Este mês</p>
            <div className="settings-usage-grid"><div><strong>{usage?.calls_month ?? 0}</strong><span>respostas</span></div><div><strong>{usage?.input_tokens_month ?? 0}</strong><span>tokens de entrada</span></div><div><strong>{usage?.output_tokens_month ?? 0}</strong><span>tokens de saída</span></div></div>
            <div className="settings-cost-row"><span>Custo estimado</span><strong>{status?.provider === "ollama" ? "Sem cobrança por tokens" : status?.provider === "chatgpt_plan" ? "Incluído no Plus" : formatUsdCost(usage?.cost_usd_month)}</strong></div>
            <p className="settings-help">{status?.provider === "ollama" ? "O modelo roda na VM e não cobra tokens de API. O processamento usa os recursos da própria máquina." : "As respostas usam a cota compartilhada da sua conta ChatGPT Plus. A SophIA não usa chave de API nem tem fallback pago. O histórico e as preferências permanecem no PostgreSQL da SophIA."}</p>
          </section>
          <section className="assistant-settings-card settings-memories">
            <h2>Memórias da SophIA</h2>
            <p>O que a SophIA sabe sobre você vem das preferências e referências que você escolheu guardar. Elas não alteram lançamentos e só são usadas quando você as registra.</p>
            <fieldset className="settings-memory-examples">
              <legend>Exemplos</legend>
              <div className="settings-memory-example-options">
                <button onClick={() => chooseMemoryExample("Quero acompanhar melhor os gastos com [categoria].")} type="button">Objetivo do mês</button>
                <button onClick={() => chooseMemoryExample("Classifique compras na Padaria Central como Alimentação.")} type="button">Categoria</button>
                <button onClick={() => chooseMemoryExample("Quando eu mencionar [assunto], quero dizer [contexto].")} type="button">Contexto</button>
              </div>
            </fieldset>
            <form className="settings-memory-form" data-scroll-editor="true" onSubmit={(event) => void submitMemory(event)} ref={memoryEditorRef}>
              <label className="settings-memory-label" data-editor-heading htmlFor="assistant-preference" tabIndex={-1}>Lembrete para a SophIA</label>
              <p className="settings-memory-help" id="assistant-memory-help">Escreva uma frase específica. Você poderá editar ou remover essa memória depois.</p>
              <textarea
                aria-describedby="assistant-memory-help"
                id="assistant-preference"
                maxLength={500}
                onChange={(event) => setMemoryDraft(event.target.value)}
                placeholder="Ex.: Prefiro registrar compras no mercado na categoria Alimentação."
                rows={4}
                value={memoryDraft}
              />
              <div className="settings-memory-form-footer">
                <span>{memoryDraft.length}/500 caracteres</span>
                <div>
                  {editingMemoryId && <button className="settings-memory-cancel" onClick={() => { setEditingMemoryId(null); setMemoryDraft(""); setMemoryError(""); }} type="button">Cancelar edição</button>}
                  <button className="settings-memory-save" disabled={savingMemory || !memoryDraft.trim()} type="submit">{savingMemory ? "Salvando…" : editingMemoryId ? "Salvar memória" : "Adicionar memória"}</button>
                </div>
              </div>
              {memoryError && <p className="settings-memory-error" role="alert">{memoryError}</p>}
            </form>
            <div className="settings-memory-list-heading"><strong>Lembretes ativos</strong><span>{visibleMemories.length}</span></div>
            {visibleMemories.length === 0 ? <div className="settings-memory-empty">Nenhum lembrete adicional. As escolhas estruturadas ficam em “Meu Assistente”.</div> : <>{memoryPagination.items.map((memory) => <div className="settings-memory-row" key={memory.id}><span>{memory.content}</span><div><button aria-label={`Editar preferência: ${memory.content}`} onClick={() => editMemory(memory)} type="button">Editar</button><button aria-label={`Remover preferência: ${memory.content}`} onClick={() => onDeleteMemory(memory.id)} type="button">Remover</button></div></div>)}<PaginationControls end={memoryPagination.end} label="Paginação das memórias da SophIA" onPageChange={memoryPagination.setPage} page={memoryPagination.page} pageCount={memoryPagination.pageCount} start={memoryPagination.start} total={memoryPagination.total} /></>}
          </section>
          <section className="assistant-settings-card settings-assistant-preferences">
            <div className="settings-card-heading"><div><p className="eyebrow">Personalização explícita</p><h2>Como a SophIA trabalha com você</h2></div></div>
            <p>Defina como a SophIA deve conversar e qual contexto priorizar. Só estas escolhas explícitas serão consideradas; não há aprendizado automático silencioso.</p>
            <div className="assistant-preferences-grid">
              <label className="assistant-preference-field">Estilo de resposta
                <select onChange={(event) => updateAssistantPreference("responseStyle", event.target.value as AssistantPreferences["responseStyle"])} value={assistantPreferences.responseStyle}>
                  <option value="concise">Curto e direto</option><option value="balanced">Equilibrado</option><option value="detailed">Mais detalhado</option>
                </select>
              </label>
              <label className="assistant-preference-field">Conta padrão
                <select onChange={(event) => updateAssistantPreference("defaultAccount", event.target.value)} value={assistantPreferences.defaultAccount}>
                  <option value="">Perguntar quando necessário</option>
                  {assistantPreferences.defaultAccount && !accounts.some((account) => account.name === assistantPreferences.defaultAccount) && <option value={assistantPreferences.defaultAccount}>{assistantPreferences.defaultAccount} (indisponível)</option>}
                  {accounts.filter((account) => account.is_active).map((account) => <option key={account.id} value={account.name}>{account.name}</option>)}
                </select>
              </label>
              <label className="assistant-preference-field">Cartão principal
                <select onChange={(event) => updateAssistantPreference("mainCard", event.target.value)} value={assistantPreferences.mainCard}>
                  <option value="">Perguntar quando necessário</option>
                  {assistantPreferences.mainCard && !cards.some((card) => card.name === assistantPreferences.mainCard) && <option value={assistantPreferences.mainCard}>{assistantPreferences.mainCard} (indisponível)</option>}
                  {cards.map((card) => <option key={card.id} value={card.name}>{card.name}</option>)}
                </select>
              </label>
              <label className="assistant-preference-field">Quando faltar contexto
                <select onChange={(event) => updateAssistantPreference("ambiguityBehavior", event.target.value as AssistantPreferences["ambiguityBehavior"])} value={assistantPreferences.ambiguityBehavior}>
                  <option value="ask">Perguntar antes de agir</option><option value="use_context">Usar o contexto quando estiver claro</option>
                </select>
              </label>
              <label className="assistant-preference-field">Proatividade
                <select onChange={(event) => updateAssistantPreference("proactivity", event.target.value as AssistantPreferences["proactivity"])} value={assistantPreferences.proactivity}>
                  <option value="on_request">Só quando eu perguntar</option><option value="relevant">Sugerir alertas relevantes</option>
                </select>
              </label>
            </div>
            <div className="assistant-preferences-footer">
              <span aria-live="polite">{assistantPreferencesError ? <span className="settings-form-error" role="alert">{assistantPreferencesError}</span> : assistantPreferencesSaved ? "Preferências salvas." : "Você pode alterar estas escolhas quando quiser."}</span>
              <button className="settings-memory-save" disabled={savingAssistantPreferences} onClick={() => void saveAssistantPreferences()} type="button">{savingAssistantPreferences ? "Salvando…" : "Salvar preferências"}</button>
            </div>
          </section>
          <section className="assistant-settings-card settings-appearance">
            <h2>Aparência</h2>
            <p>Escolha um ambiente claro para o dia ou escuro para sessões mais longas. A escolha fica salva neste navegador.</p>
            <fieldset className="settings-theme-group">
              <legend>Tema da interface</legend>
              <div className="settings-theme-options">
                <button aria-pressed={theme === "light"} className={theme === "light" ? "settings-theme-option selected" : "settings-theme-option"} onClick={() => onThemeChange("light")} type="button"><Sun aria-hidden="true" size={17} />Claro</button>
                <button aria-pressed={theme === "dark"} className={theme === "dark" ? "settings-theme-option selected" : "settings-theme-option"} onClick={() => onThemeChange("dark")} type="button"><Moon aria-hidden="true" size={17} />Escuro</button>
              </div>
            </fieldset>
          </section>
          {status?.diagnostics_enabled && (
            <section className="assistant-settings-card settings-diagnostics">
              <h2>Diagnóstico da SophIA</h2>
              <p>Somente neste ambiente de desenvolvimento. Mensagens, instruções internas e credenciais não são exibidas.</p>
              {diagnostics.length === 0 ? (
                <div className="settings-memory-empty">Nenhuma interação recente.</div>
              ) : (
                <div className="settings-diagnostic-list">
                  {diagnosticsPagination.items.map((item) => (
                    <article className="settings-diagnostic-row" key={item.id}>
                      <div className="settings-diagnostic-heading">
                        <strong>{item.tool_name ?? "Resposta do assistente"}</strong>
                        <span>{diagnosticStatusLabel(item.status)}</span>
                      </div>
                      <div className="settings-diagnostic-meta">
                        <span>{displayTimestamp(item.created_at)}</span>
                        <span>Conversa {item.conversation_id.slice(0, 8)}</span>
                        <span>{item.model ?? "Modelo indisponível"}</span>
                        <span>{item.duration_ms === null ? "Duração indisponível" : `${item.duration_ms} ms`}</span>
                      </div>
                      <div className="settings-diagnostic-meta">
                        <span>Entrada: {item.input_tokens ?? "—"}</span>
                        <span>Em cache: {item.cached_input_tokens ?? "—"}</span>
                        <span>Saída: {item.output_tokens ?? "—"}</span>
                        <span>Custo: {formatUsdCost(item.estimated_cost_usd)}</span>
                      </div>
                      <div className="settings-diagnostic-meta">
                        <span>Preparo: {item.preparation_ms === null ? "—" : `${(item.preparation_ms / 1000).toFixed(1)} s`}</span>
                        <span>1ª saída do modelo: {item.first_output_ms === null ? "—" : `${(item.first_output_ms / 1000).toFixed(1)} s`}</span>
                        <span>1º texto: {item.first_text_ms === null ? "—" : `${(item.first_text_ms / 1000).toFixed(1)} s`}</span>
                        <span>Ferramentas disponíveis: {item.available_tool_count ?? "—"}</span>
                      </div>
                      {item.error_summary && <p className="settings-diagnostic-error">{item.error_summary}</p>}
                    </article>
                  ))}
                  <PaginationControls end={diagnosticsPagination.end} label="Paginação dos diagnósticos" onPageChange={diagnosticsPagination.setPage} page={diagnosticsPagination.page} pageCount={diagnosticsPagination.pageCount} start={diagnosticsPagination.start} total={diagnosticsPagination.total} />
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </section>
  );
}

type AccountSession = {
  created_at: string;
  expires_at: string;
  is_current: boolean;
};

function formatAccountDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Data indisponível";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "America/Sao_Paulo",
  }).format(date);
}

function AccountView({
  avatarUrl,
  displayName,
  email,
  mfaRequired,
  mfaEnrolled,
  onAvatarUrlChange,
  onDisplayNameChange,
  onLogout,
}: {
  avatarUrl: string | null;
  displayName: string;
  email: string;
  mfaRequired: boolean;
  mfaEnrolled: boolean;
  onAvatarUrlChange: (avatarUrl: string | null) => void;
  onDisplayNameChange: (displayName: string) => void;
  onLogout: () => void;
}) {
  const [nameDraft, setNameDraft] = useState(displayName);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const [exportingData, setExportingData] = useState(false);
  const avatarInputRef = useRef<HTMLInputElement>(null);
  const [sessions, setSessions] = useState<AccountSession[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [sessionError, setSessionError] = useState("");
  const [accountError, setAccountError] = useState("");
  const [notice, setNotice] = useState("");
  const sessionsPagination = usePagination(sessions, String(sessions.length));
  const [savingProfile, setSavingProfile] = useState(false);
  const [passwordFormOpen, setPasswordFormOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordTotp, setPasswordTotp] = useState("");
  const [changingPassword, setChangingPassword] = useState(false);
  const [sessionFormOpen, setSessionFormOpen] = useState(false);
  const [sessionPassword, setSessionPassword] = useState("");
  const [sessionTotp, setSessionTotp] = useState("");
  const [revokingSessions, setRevokingSessions] = useState(false);
  const [mfaRotationStep, setMfaRotationStep] = useState<"closed" | "reauth" | "confirm">("closed");
  const [mfaRotationPassword, setMfaRotationPassword] = useState("");
  const [mfaRotationCurrentCode, setMfaRotationCurrentCode] = useState("");
  const [mfaRotationNewCode, setMfaRotationNewCode] = useState("");
  const [mfaRotationQr, setMfaRotationQr] = useState("");
  const [mfaRotationManualKey, setMfaRotationManualKey] = useState("");
  const [mfaRotationExpiresAt, setMfaRotationExpiresAt] = useState("");
  const [rotatingMfa, setRotatingMfa] = useState(false);

  const loadSessions = useCallback(async () => {
    setLoadingSessions(true);
    setSessionError("");
    try {
      const activeSessions = await apiRequest<AccountSession[]>("/api/auth/sessions");
      setSessions(activeSessions);
    } catch (error) {
      setSessionError(error instanceof Error ? error.message : "Não foi possível consultar as sessões.");
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    setNameDraft(displayName);
  }, [displayName]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = nameDraft.trim();
    if (!normalizedName || normalizedName === displayName) return;
    setSavingProfile(true);
    setAccountError("");
    setNotice("");
    try {
      const updated = await apiRequest<{ display_name: string }>("/api/auth/me", {
        method: "PATCH",
        body: JSON.stringify({ display_name: normalizedName }),
      });
      setNameDraft(updated.display_name);
      onDisplayNameChange(updated.display_name);
      setNotice("Nome atualizado.");
    } catch (error) {
      setAccountError(error instanceof Error ? error.message : "Não foi possível salvar seu nome.");
    } finally {
      setSavingProfile(false);
    }
  }

  async function uploadAvatar(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    setAccountError("");
    setNotice("");
    if (!("image/jpeg" === file.type || "image/png" === file.type || "image/webp" === file.type)) {
      setAccountError("Escolha uma imagem JPEG, PNG ou WebP.");
      return;
    }
    if (file.size > 25 * 1024 * 1024) {
      setAccountError("A foto original precisa ter até 25 MB.");
      return;
    }

    setUploadingAvatar(true);
    try {
      const bitmap = await createImageBitmap(file);
      if (bitmap.width * bitmap.height > 48_000_000) {
        bitmap.close();
        throw new Error("A foto pode ter no máximo 48 megapixels.");
      }
      const scale = Math.min(1, 512 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const context = canvas.getContext("2d");
      if (!context) {
        bitmap.close();
        throw new Error("Não foi possível preparar essa imagem.");
      }
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      bitmap.close();
      const imageDataUrl = canvas.toDataURL("image/webp", 0.84);
      const updated = await apiRequest<{ avatar_url: string | null }>("/api/auth/me/avatar", {
        method: "PUT",
        body: JSON.stringify({ image_data_url: imageDataUrl }),
      });
      onAvatarUrlChange(updated.avatar_url);
      setNotice("Foto de perfil atualizada.");
    } catch (error) {
      setAccountError(error instanceof Error ? error.message : "Não foi possível salvar a foto.");
    } finally {
      setUploadingAvatar(false);
    }
  }

  async function removeAvatar() {
    setAccountError("");
    setNotice("");
    setUploadingAvatar(true);
    try {
      const updated = await apiRequest<{ avatar_url: string | null }>("/api/auth/me/avatar", {
        method: "DELETE",
      });
      onAvatarUrlChange(updated.avatar_url);
      setNotice("Foto removida.");
    } catch (error) {
      setAccountError(error instanceof Error ? error.message : "Não foi possível remover a foto.");
    } finally {
      setUploadingAvatar(false);
    }
  }

  async function downloadFinanceExport() {
    setExportingData(true);
    setAccountError("");
    setNotice("");
    try {
      const response = await fetch("/api/export", {
        headers: { "X-SophIA-Request": "1" },
        cache: "no-store",
      });
      if (!response.ok) {
        let message = "Não foi possível exportar seus dados financeiros.";
        try {
          const body: unknown = await response.json();
          if (typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string") {
            message = body.detail;
          }
        } catch {
          // Mantém a mensagem segura para respostas sem JSON.
        }
        throw new Error(message);
      }

      const filenameHeader = response.headers.get("Content-Disposition") ?? "";
      const filenameMatch = filenameHeader.match(/filename="([a-zA-Z0-9._-]+)"/);
      const filename = filenameMatch?.[1] ?? "sophia-financas.json";
      const downloadUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
      setNotice("Cópia dos seus dados financeiros baixada.");
    } catch (error) {
      setAccountError(error instanceof Error ? error.message : "Não foi possível exportar seus dados financeiros.");
    } finally {
      setExportingData(false);
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAccountError("");
    setNotice("");
    if (newPassword !== confirmPassword) {
      setAccountError("As senhas novas não conferem.");
      return;
    }
    setChangingPassword(true);
    try {
      await apiRequest<{ status: string }>("/api/auth/password/change", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
          ...(passwordTotp ? { totp_code: passwordTotp } : {}),
        }),
      });
      setNotice("Senha alterada. Entre novamente com a nova senha e o MFA.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordTotp("");
      setPasswordFormOpen(false);
      await onLogout();
    } catch (error) {
      setAccountError(error instanceof Error ? error.message : "Não foi possível alterar a senha.");
    } finally {
      setChangingPassword(false);
    }
  }

  async function revokeOtherSessions(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAccountError("");
    setNotice("");
    setRevokingSessions(true);
    try {
      const result = await apiRequest<{ revoked_count: number }>("/api/auth/sessions/revoke-others", {
        method: "POST",
        body: JSON.stringify({
          current_password: sessionPassword,
          ...(sessionTotp ? { totp_code: sessionTotp } : {}),
        }),
      });
      setNotice(result.revoked_count === 1 ? "1 sessão foi encerrada." : `${result.revoked_count} sessões foram encerradas.`);
      setSessionPassword("");
      setSessionTotp("");
      setSessionFormOpen(false);
      await loadSessions();
    } catch (error) {
      setAccountError(error instanceof Error ? error.message : "Não foi possível encerrar as outras sessões.");
    } finally {
      setRevokingSessions(false);
    }
  }

  async function startMfaRotation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAccountError("");
    setNotice("");
    setRotatingMfa(true);
    try {
      const enrollment = await apiRequest<{ qr_code_data_url: string; manual_key: string; expires_at: string }>("/api/auth/mfa/enrollment/start", {
        method: "POST",
        body: JSON.stringify({ email, password: mfaRotationPassword, totp_code: mfaRotationCurrentCode }),
      });
      setMfaRotationQr(enrollment.qr_code_data_url);
      setMfaRotationManualKey(enrollment.manual_key);
      setMfaRotationExpiresAt(enrollment.expires_at);
      setMfaRotationStep("confirm");
      setMfaRotationCurrentCode("");
    } catch (error) {
      setAccountError(error instanceof Error ? error.message : "Não foi possível iniciar a troca do autenticador.");
      setMfaRotationCurrentCode("");
    } finally {
      setRotatingMfa(false);
    }
  }

  async function confirmMfaRotation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAccountError("");
    setNotice("");
    setRotatingMfa(true);
    try {
      await apiRequest<{ mfa_enrolled: boolean }>("/api/auth/mfa/enrollment/confirm", {
        method: "POST",
        body: JSON.stringify({ email, password: mfaRotationPassword, totp_code: mfaRotationNewCode }),
      });
      setNotice("Autenticador trocado. Entre novamente usando o novo código MFA.");
      setMfaRotationPassword("");
      setMfaRotationNewCode("");
      setMfaRotationQr("");
      setMfaRotationManualKey("");
      setMfaRotationExpiresAt("");
      setMfaRotationStep("closed");
      await onLogout();
    } catch (error) {
      setAccountError(error instanceof Error ? error.message : "Não foi possível confirmar o novo autenticador.");
      setMfaRotationNewCode("");
    } finally {
      setRotatingMfa(false);
    }
  }

  function cancelMfaRotation() {
    setMfaRotationStep("closed");
    setMfaRotationPassword("");
    setMfaRotationCurrentCode("");
    setMfaRotationNewCode("");
    setMfaRotationQr("");
    setMfaRotationManualKey("");
    setMfaRotationExpiresAt("");
    setAccountError("");
  }

  const otherSessionCount = sessions.filter((session) => !session.is_current).length;

  return (
    <section className="assistant-settings-page account-page">
      <div className="assistant-settings-heading">
        <p className="assistant-eyebrow">Acesso privado</p>
        <h1>Minha conta</h1>
        <p>Gerencie seu perfil, sua senha e os acessos ativos à SophIA.</p>
      </div>
      {(accountError || notice) && (
        <div aria-live="polite" className={accountError ? "account-feedback error" : "account-feedback"} role={accountError ? "alert" : "status"}>
          {accountError || notice}
        </div>
      )}
      <div className="assistant-settings-grid account-grid">
        <section className="assistant-settings-card account-card">
          <h2>Perfil</h2>
          <div className="account-avatar-editor">
            <span className="account-avatar-preview" aria-hidden="true">{avatarUrl ? <Image alt="" decoding="async" height={58} src={avatarUrl} unoptimized width={58} /> : displayName.slice(0, 1).toUpperCase()}</span>
            <div className="account-avatar-copy">
              <strong>Foto de perfil</strong>
              <p>JPEG, PNG ou WebP · foto original até 25 MB. A imagem é reduzida para caber no perfil.</p>
              <input accept="image/jpeg,image/png,image/webp" aria-label="Escolher foto de perfil" hidden onChange={(event) => void uploadAvatar(event)} ref={avatarInputRef} type="file" />
              <div className="account-avatar-actions">
                <button className="secondary-button" disabled={uploadingAvatar} onClick={() => avatarInputRef.current?.click()} type="button">{uploadingAvatar ? "Salvando…" : avatarUrl ? "Trocar foto" : "Adicionar foto"}</button>
                {avatarUrl && <button className="text-button account-avatar-remove" disabled={uploadingAvatar} onClick={() => void removeAvatar()} type="button">Remover</button>}
              </div>
            </div>
          </div>
          <form className="account-form" onSubmit={(event) => void saveProfile(event)}>
            <label className="account-form-field" htmlFor="account-display-name">Nome de exibição
              <input id="account-display-name" autoComplete="name" maxLength={100} onChange={(event) => setNameDraft(event.target.value)} required value={nameDraft} />
            </label>
            <label className="account-form-field" htmlFor="account-email">E-mail de acesso
              <input id="account-email" autoComplete="username" readOnly value={email} />
            </label>
            <div className="account-card-actions">
              <span>O e-mail é usado para entrar na sua conta.</span>
              <button className="settings-memory-save" disabled={savingProfile || !nameDraft.trim() || nameDraft.trim() === displayName} type="submit">{savingProfile ? "Salvando…" : "Salvar nome"}</button>
            </div>
          </form>
        </section>

        <section className="assistant-settings-card account-card">
          <h2>Proteção da conta</h2>
          <div className="settings-row"><span>Autenticação em duas etapas</span><strong className={mfaRequired && mfaEnrolled ? "settings-state ready" : "settings-state"}>{mfaRequired && mfaEnrolled ? "Ativa · TOTP" : mfaRequired ? "Configuração pendente" : "Não obrigatória neste ambiente"}</strong></div>
          <p className="settings-help">{mfaRequired ? "O código do Authy é solicitado depois da senha. Para trocar o autenticador, confirme sua senha e o código atual." : "O TOTP está configurado por ambiente. Em produção, mantenha a verificação obrigatória ativa."}</p>
          {mfaRequired && mfaEnrolled && mfaRotationStep === "closed" && <button className="secondary-button account-secondary-action" onClick={() => { setAccountError(""); setMfaRotationStep("reauth"); }} type="button">Trocar autenticador</button>}
          {mfaRotationStep === "reauth" && (
            <form className="account-form account-password-form" onSubmit={(event) => void startMfaRotation(event)}>
              <p className="settings-help">Confirme sua senha e use um código atual que ainda não tenha sido usado. O QR vale por dez minutos, e seu autenticador atual continua funcionando até você confirmar o novo.</p>
              <label className="account-form-field" htmlFor="account-mfa-current-password">Senha atual
                <input autoComplete="current-password" id="account-mfa-current-password" minLength={12} name="current_password" onChange={(event) => setMfaRotationPassword(event.target.value)} required type="password" value={mfaRotationPassword} />
              </label>
              <label className="account-form-field" htmlFor="account-mfa-current-code">Código atual do Authy
                <input autoComplete="one-time-code" id="account-mfa-current-code" inputMode="numeric" maxLength={6} minLength={6} name="current_totp_code" onChange={(event) => setMfaRotationCurrentCode(event.target.value.replace(/\D/g, "").slice(0, 6))} pattern="\d{6}" required spellCheck={false} value={mfaRotationCurrentCode} />
              </label>
              <div className="account-form-actions">
                <button className="secondary-button" onClick={cancelMfaRotation} type="button">Cancelar</button>
                <button className="settings-memory-save" disabled={rotatingMfa} type="submit">{rotatingMfa ? "Gerando QR…" : "Gerar novo QR"}</button>
              </div>
            </form>
          )}
          {mfaRotationStep === "confirm" && (
            <form className="account-form account-password-form" onSubmit={(event) => void confirmMfaRotation(event)}>
              <div className="mfa-enrollment-qr-panel">
                <Image alt="QR code para configurar o novo autenticador da SophIA" className="mfa-enrollment-qr" height={240} src={mfaRotationQr} unoptimized width={240} />
                <p>Escaneie com o Authy. O QR expira às {new Date(mfaRotationExpiresAt).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo" })} (horário de São Paulo). O autenticador atual continua válido até a confirmação.</p>
                <details>
                  <summary>Precisa inserir manualmente?</summary>
                  <p>Adicione uma conta TOTP no Authy e informe esta chave temporária:</p>
                  <code>{mfaRotationManualKey}</code>
                </details>
              </div>
              <label className="account-form-field" htmlFor="account-mfa-new-code">Código do novo autenticador
                <input autoComplete="one-time-code" id="account-mfa-new-code" inputMode="numeric" maxLength={6} minLength={6} name="new_totp_code" onChange={(event) => setMfaRotationNewCode(event.target.value.replace(/\D/g, "").slice(0, 6))} pattern="\d{6}" required spellCheck={false} value={mfaRotationNewCode} />
              </label>
              <p className="settings-help">Ao confirmar, o novo autenticador substitui o atual e todos os acessos serão encerrados. Entre novamente com o novo código.</p>
              <div className="account-form-actions">
                <button className="secondary-button" onClick={cancelMfaRotation} type="button">Cancelar</button>
                <button className="settings-memory-save" disabled={rotatingMfa} type="submit">{rotatingMfa ? "Confirmando…" : "Confirmar novo autenticador"}</button>
              </div>
            </form>
          )}
          {!passwordFormOpen ? (
            <button className="secondary-button account-secondary-action" onClick={() => { setAccountError(""); setPasswordFormOpen(true); }} type="button">Alterar senha</button>
          ) : (
            <form className="account-form account-password-form" onSubmit={(event) => void changePassword(event)}>
              <label className="account-form-field" htmlFor="account-current-password">Senha atual
                <input autoComplete="current-password" id="account-current-password" minLength={12} onChange={(event) => setCurrentPassword(event.target.value)} required type="password" value={currentPassword} />
              </label>
              <label className="account-form-field" htmlFor="account-new-password">Nova senha
                <input autoComplete="new-password" id="account-new-password" minLength={12} onChange={(event) => setNewPassword(event.target.value)} required type="password" value={newPassword} />
              </label>
              <label className="account-form-field" htmlFor="account-confirm-password">Confirme a nova senha
                <input autoComplete="new-password" id="account-confirm-password" minLength={12} onChange={(event) => setConfirmPassword(event.target.value)} required type="password" value={confirmPassword} />
              </label>
              {mfaRequired && <label className="account-form-field" htmlFor="account-password-totp">Código atual do Authy
                <input autoComplete="one-time-code" id="account-password-totp" inputMode="numeric" maxLength={6} minLength={6} onChange={(event) => setPasswordTotp(event.target.value.replace(/\D/g, "").slice(0, 6))} pattern="\d{6}" required value={passwordTotp} />
              </label>}
              <p className="settings-help">Ao trocar a senha, todos os acessos serão encerrados e você precisará entrar novamente.</p>
              <div className="account-form-actions">
                <button className="secondary-button" onClick={() => { setPasswordFormOpen(false); setCurrentPassword(""); setNewPassword(""); setConfirmPassword(""); setPasswordTotp(""); }} type="button">Cancelar</button>
                <button className="settings-memory-save" disabled={changingPassword || currentPassword.length < 12 || newPassword.length < 12 || (mfaRequired && passwordTotp.length !== 6)} type="submit">{changingPassword ? "Alterando…" : "Trocar senha"}</button>
              </div>
            </form>
          )}
        </section>

        <section className="assistant-settings-card account-card account-sessions-card">
          <div className="account-section-heading"><div><h2>Sessões ativas</h2><p>A sessão atual permanece ativa quando você encerra os outros acessos.</p></div><span>{loadingSessions ? "…" : sessions.length}</span></div>
          {sessionError ? <p className="account-inline-error" role="alert">{sessionError}</p> : loadingSessions ? <p className="settings-help">Consultando sessões…</p> : sessions.length === 0 ? <p className="settings-help">Nenhuma sessão ativa encontrada.</p> : (
            <div className="account-session-list">
              {sessionsPagination.items.map((session) => (
                <div className="account-session-row" key={`${session.created_at}-${session.expires_at}`}>
                  <span><strong>{session.is_current ? "Este dispositivo" : "Outro acesso"}</strong><small>Entrou em {formatAccountDate(session.created_at)} · expira em {formatAccountDate(session.expires_at)}</small></span>
                  {session.is_current && <span className="account-current-badge">Atual</span>}
                </div>
              ))}
              <PaginationControls end={sessionsPagination.end} label="Paginação das sessões ativas" onPageChange={sessionsPagination.setPage} page={sessionsPagination.page} pageCount={sessionsPagination.pageCount} start={sessionsPagination.start} total={sessionsPagination.total} />
            </div>
          )}
          {otherSessionCount > 0 && !sessionFormOpen && <button className="secondary-button account-secondary-action" onClick={() => { setAccountError(""); setSessionFormOpen(true); }} type="button">Encerrar outros acessos</button>}
          {sessionFormOpen && (
            <form className="account-form account-revoke-form" onSubmit={(event) => void revokeOtherSessions(event)}>
              <p className="settings-help">Confirme sua identidade para encerrar {otherSessionCount === 1 ? "o outro acesso" : `os ${otherSessionCount} outros acessos`}.</p>
              <label className="account-form-field" htmlFor="account-session-password">Senha atual
                <input autoComplete="current-password" id="account-session-password" minLength={12} onChange={(event) => setSessionPassword(event.target.value)} required type="password" value={sessionPassword} />
              </label>
              {mfaRequired && <label className="account-form-field" htmlFor="account-session-totp">Código atual do Authy
                <input autoComplete="one-time-code" id="account-session-totp" inputMode="numeric" maxLength={6} minLength={6} onChange={(event) => setSessionTotp(event.target.value.replace(/\D/g, "").slice(0, 6))} pattern="\d{6}" required value={sessionTotp} />
              </label>}
              <div className="account-form-actions">
                <button className="secondary-button" onClick={() => { setSessionFormOpen(false); setSessionPassword(""); setSessionTotp(""); }} type="button">Cancelar</button>
                <button className="settings-memory-save" disabled={revokingSessions || sessionPassword.length < 12 || (mfaRequired && sessionTotp.length !== 6)} type="submit">{revokingSessions ? "Encerrando…" : "Confirmar encerramento"}</button>
              </div>
            </form>
          )}
        </section>

        <section className="assistant-settings-card account-card account-export-card">
          <div>
            <h2>Seus dados</h2>
            <p className="settings-help">Baixe uma cópia JSON dos seus registros financeiros para guardar ou transportar. O arquivo contém dados pessoais; mantenha-o em local protegido.</p>
          </div>
          <button className="secondary-button account-secondary-action" disabled={exportingData} onClick={() => void downloadFinanceExport()} type="button">
            {exportingData ? "Preparando cópia…" : "Baixar meus dados"}
          </button>
        </section>
      </div>
    </section>
  );
}
