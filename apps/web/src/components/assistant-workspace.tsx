"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import {
  Archive,
  ArrowDownLeft,
  ArrowLeftRight,
  ArrowUp,
  ArrowUpRight,
  ChartNoAxesCombined,
  CreditCard,
  Landmark,
  LayoutDashboard,
  LogOut,
  Menu,
  MoreHorizontal,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightOpen,
  Plus,
  Pencil,
  ReceiptText,
  Repeat2,
  SlidersHorizontal,
  Sun,
  Tags,
  WalletCards,
  X,
  type LucideIcon,
} from "lucide-react";

import { FinanceWorkspace } from "@/components/finance-workspace";
import { FirstUseSetup } from "@/components/first-use-setup";
import { ApiError, apiRequest } from "@/lib/api";
import { formatCurrency } from "@/lib/money";

type FinanceSection = "overview" | "transactions" | "accounts" | "categories" | "cards" | "recurrences";
type WorkspaceView = "chat" | "finance" | "settings";
type Theme = "light" | "dark";

type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

type StructuredItem = {
  type: string;
  data?: unknown;
  tool_call_id?: string;
  status?: string;
};

type AssistantMessage = {
  id: string;
  role: "USER" | "ASSISTANT";
  content: string;
  structured_content?: StructuredItem[] | null;
  pending?: boolean;
};

let optimisticMessageSequence = 0;

function createOptimisticMessageId() {
  optimisticMessageSequence += 1;
  return `optimistic-${Date.now()}-${optimisticMessageSequence}`;
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
  period_start: string;
  period_end: string;
  total_balance: string | null;
  incomplete_account_count: number;
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
};

type ContextAccount = { id: string; name: string; balance: string | null; is_active: boolean };
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

function displayMonth(value: string): string {
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return "Este mês";
  return new Intl.DateTimeFormat("pt-BR", {
    month: "long",
    year: "numeric",
    timeZone: "America/Sao_Paulo",
  }).format(parsed);
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
  displayName,
  onLogout,
  theme,
  onThemeChange,
}: {
  displayName: string;
  onLogout: () => void;
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
}) {
  const [view, setView] = useState<WorkspaceView>("chat");
  const [financeSection, setFinanceSection] = useState<FinanceSection>("overview");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [contextAccounts, setContextAccounts] = useState<ContextAccount[]>([]);
  const [contextCards, setContextCards] = useState<ContextCard[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [diagnostics, setDiagnostics] = useState<AIDiagnostic[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [draft, setDraft] = useState("");
  const [greeting, setGreeting] = useState("Olá");
  const [loading, setLoading] = useState(true);
  const [firstUseRequired, setFirstUseRequired] = useState<boolean | null>(null);
  const [sending, setSending] = useState(false);
  const [loadingSettings, setLoadingSettings] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [activeTool, setActiveTool] = useState("");
  const [error, setError] = useState("");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [contextPanelOpen, setContextPanelOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [conversationMenuId, setConversationMenuId] = useState<string | null>(null);
  const [editingConversationId, setEditingConversationId] = useState<string | null>(null);
  const [conversationTitleDraft, setConversationTitleDraft] = useState("");
  const [busyConversationId, setBusyConversationId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const conversationRenameRef = useRef<HTMLInputElement>(null);

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

  useEffect(() => {
    setGreeting(currentGreeting());
    let mounted = true;
    async function loadInitialData() {
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
  }, [loadDashboard]);

  function completeFirstUse() {
    setFirstUseRequired(false);
    void loadDashboard();
  }

  function openCardsFromFirstUse() {
    setFirstUseRequired(false);
    setFinanceSection("cards");
    setView("finance");
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
    setView("chat");
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
    setView("chat");
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

  async function sendMessage(content: string) {
    const clean = content.trim();
    if (!clean || sending || status?.configured !== true) return;
    setError("");
    setDraft("");
    if (composerRef.current) composerRef.current.style.height = "42px";
    setSending(true);
    setActiveTool("");
    let activeConversationId = conversationId;
    try {
      if (!activeConversationId) {
        const created = await apiRequest<Conversation & { messages: AssistantMessage[] }>(
          "/api/ai/conversations",
          { method: "POST", body: JSON.stringify({}) },
        );
        activeConversationId = created.id;
        setConversationId(created.id);
      }

      const userMessage: AssistantMessage = {
        id: createOptimisticMessageId(),
        role: "USER",
        content: clean,
      };
      const assistantId = createOptimisticMessageId();
      setMessages((current) => [
        ...current,
        userMessage,
        { id: assistantId, role: "ASSISTANT", content: "", pending: true },
      ]);

      const response = await fetch(`/api/ai/conversations/${activeConversationId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ content: clean }),
        cache: "no-store",
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
            setActiveTool(toolStatus === "running" ? `Consultando ${toolLabel(name)}…` : "");
          } else if (eventName === "done") {
            setActiveTool("");
          }
        }
      }

      await Promise.all([loadConversation(activeConversationId), loadConversations(), loadDashboard()]);
    } catch (sendError) {
      const message = sendError instanceof Error ? sendError.message : "Não foi possível concluir a mensagem.";
      setError(message);
      setMessages((current) => current.filter((item) => !item.pending));
    } finally {
      setActiveTool("");
      setSending(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await sendMessage(draft);
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage(draft);
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

  async function openSettings() {
    setView("settings");
    setMobileMenuOpen(false);
    setContextPanelOpen(false);
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
    setConversationMenuId(null);
    setEditingConversationId(null);
    if (item.view === "settings") {
      void openSettings();
    } else {
      setView(item.view);
      if (item.section) setFinanceSection(item.section);
      setMobileMenuOpen(false);
    }
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
    setContextPanelOpen(Boolean(contextPanelAvailable && (showWelcome || hasUsefulContext)));
  }, [contextPanelAvailable, showWelcome, hasUsefulContext]);
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
        placeholder="Pergunte sobre suas finanças…"
        ref={composerRef}
        rows={1}
        value={draft}
      />
      <div className="assistant-composer-footer">
        <span>Enter envia · Shift + Enter quebra linha</span>
        <button aria-label="Enviar mensagem" disabled={sending || !draft.trim()} type="submit">{sending ? <span className="assistant-spinner" /> : <ArrowUp aria-hidden="true" size={19} />}</button>
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
    <div className={sidebarCollapsed ? "assistant-layout sidebar-collapsed" : "assistant-layout"} data-theme={theme}>
      {mobileMenuOpen && <button aria-label="Fechar menu" className="assistant-backdrop" onClick={() => setMobileMenuOpen(false)} type="button" />}
      {contextPanelOpen && contextPanelAvailable && <button aria-label="Fechar contexto" className="assistant-context-backdrop" onClick={() => setContextPanelOpen(false)} type="button" />}
      <aside className={mobileMenuOpen ? "assistant-sidebar mobile-open" : "assistant-sidebar"}>
        <button aria-label="Ir para a visão geral" className="assistant-brand" onClick={() => chooseNavigation(NAV_ITEMS[0])} type="button">
          <span className="assistant-brand-mark" aria-hidden="true">S</span>
          <span className="assistant-brand-name">SophIA</span>
        </button>
        <button className="assistant-new-chat" onClick={startConversation} type="button">
          <Plus aria-hidden="true" size={17} strokeWidth={2} /><span>Nova conversa</span>
        </button>
        <div className="assistant-history">
          <p>Conversas recentes</p>
          {loading ? <span className="history-placeholder">Carregando…</span> : conversations.length === 0 ? (
            <span className="history-placeholder">Pergunte sobre seus gastos para começar.</span>
          ) : conversations.map((conversation) => (
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
                  <span className="history-marker" aria-hidden="true" />
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
        </div>
        <nav className="assistant-nav" aria-label="Navegação financeira">
          <div className="assistant-nav-group">
            <p className="assistant-nav-label">Finanças</p>
            {NAV_ITEMS.filter((item) => item.view === "finance").map((item) => {
              const key = item.view === "finance" ? `finance-${item.section}` : item.view;
              return (
                <button
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
          <span className="assistant-avatar" aria-hidden="true">{displayName.slice(0, 1).toUpperCase()}</span>
          <span className="assistant-account-name">{displayName}</span>
          <button aria-label="Sair" className="assistant-logout" onClick={onLogout} title="Sair" type="button"><LogOut aria-hidden="true" size={16} /></button>
        </div>
      </aside>

      <main className="assistant-main">
        <header className="assistant-topbar">
          <button aria-label={sidebarCollapsed ? "Expandir menu lateral" : "Recolher menu lateral"} aria-pressed={sidebarCollapsed} className="assistant-sidebar-toggle" onClick={toggleDesktopSidebar} title={sidebarCollapsed ? "Expandir menu" : "Recolher menu"} type="button">{sidebarCollapsed ? <PanelLeftOpen aria-hidden="true" size={18} /> : <PanelLeftClose aria-hidden="true" size={18} />}</button>
          <button aria-label="Abrir menu" className="assistant-menu-toggle" onClick={() => setMobileMenuOpen(true)} type="button"><Menu aria-hidden="true" size={20} /></button>
          <div className="assistant-topbar-title">
            <strong>{view === "chat" ? conversations.find((conversation) => conversation.id === conversationId)?.title ?? "Nova conversa" : view === "settings" ? "Preferências" : "Finanças"}</strong>
            <span>{view === "chat" ? "SophIA · sua assistente financeira" : "Dados calculados pelo sistema"}</span>
          </div>
          <div className="assistant-topbar-actions">
          {view === "chat" && contextPanelAvailable && <button aria-expanded={contextPanelOpen} aria-label={contextPanelOpen ? "Recolher contexto financeiro" : "Abrir contexto financeiro"} className="assistant-context-toggle" onClick={() => { setMobileMenuOpen(false); setContextPanelOpen((open) => !open); }} type="button"><PanelRightOpen aria-hidden="true" size={18} /><span>Contexto</span></button>}
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
          <div className="assistant-finance-view" key={financeSection}>
            <FinanceWorkspace
              displayName={displayName}
              embedded
              initialSection={financeSection}
              onOpenAssistant={(prompt) => { startConversation(); setDraft(prompt); }}
              onLogout={onLogout}
            />
          </div>
        ) : view === "settings" ? (
          <SettingsView
            loading={loadingSettings}
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
                        {contextAccounts.length > 0 && dashboard.total_balance !== null && <span>Saldo total <strong>{formatCurrency(dashboard.total_balance)}</strong></span>}
                        {contextAccounts.length > 0 && dashboard.total_balance === null && (
                          <span>Saldo consolidado <strong>Incompleto</strong><small>{dashboard.incomplete_account_count} {dashboard.incomplete_account_count === 1 ? "conta precisa" : "contas precisam"} de saldo inicial e data-base</small></span>
                        )}
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
                    onPendingAction={(id, action) => void handlePendingAction(id, action)}
                    pendingAction={pendingAction}
                  />
                ))}
                {activeTool && <div className="assistant-tool-progress"><span className="assistant-spinner" />{activeTool}</div>}
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

function MessageBubble({
  message,
  onPendingAction,
  pendingAction,
}: {
  message: AssistantMessage;
  onPendingAction: (id: string, action: "confirm" | "cancel") => void;
  pendingAction: PendingAction;
}) {
  const userMessage = message.role === "USER";
  return (
    <article className={userMessage ? "assistant-message user-message" : "assistant-message model-message"}>
      {!userMessage && <span className="message-avatar" aria-hidden="true">S</span>}
      <div className="message-body">
        <div className="message-author">{userMessage ? "Você" : "SophIA"}</div>
        {message.content && <p className="message-text">{userMessage ? message.content : renderAssistantText(message.content)}</p>}
        {message.pending && !message.content && <span className="assistant-pending" role="status"><span className="assistant-spinner" />Respondendo</span>}
        {message.structured_content?.map((item) => (
          <StructuredCard
            item={item}
            key={`${message.id}-${item.tool_call_id ?? `${item.type}-${JSON.stringify(item.data)}`}`}
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
    const transactions = Array.isArray(item.data) ? item.data : data ? [data] : [];
    const isSingleTransfer = item.type === "transfer_card" || (transactions.length === 1 && stringValue(record(transactions[0])?.type) === "TRANSFER");
    return (
      <section className="assistant-data-card">
        <div className="assistant-data-card-heading"><span>{isSingleTransfer ? "Transferência" : transactions.length === 1 ? "Lançamento" : "Lançamentos"}</span></div>
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
    return (
      <section className="assistant-data-card">
        <div className="assistant-data-card-heading"><span>{accounts.length === 1 ? "Saldo da conta" : "Contas"}</span></div>
        <div className="assistant-transaction-list">
          {accounts.map((entry, index) => {
            const account = record(entry);
            if (!account) return null;
            const balance = stringValue(account.balance);
            return <div className="assistant-transaction-row" key={stringValue(account.id) ?? index}><span><strong>{stringValue(account.name) ?? "Conta"}</strong><small>{balance ? "Saldo disponível" : "Saldo inicial não informado"}</small></span><b>{balance ? formatCurrency(balance) : "Pendente"}</b></div>;
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
        <section className="context-balance"><span>Saldo atual das contas</span><strong>{dashboard.total_balance === null ? "Incompleto" : formatCurrency(dashboard.total_balance)}</strong><small>{dashboard.total_balance === null ? `${dashboard.incomplete_account_count} conta(s) precisam de saldo inicial e data-base` : "Soma dos saldos atuais das contas"}</small></section>
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
        <section className="context-balance"><span>Saldo total em contas</span><strong>{dashboard.total_balance === null ? (dashboard.incomplete_account_count > 0 ? "Incompleto" : "Indisponível") : formatCurrency(dashboard.total_balance)}</strong><small>{dashboard.total_balance === null ? `${dashboard.incomplete_account_count} conta(s) precisam de saldo inicial e data-base` : "Soma dos saldos atuais das contas"}</small></section>
        <div className="context-metrics context-overview-metrics">
          <div><span>Gastos em {displayMonth(dashboard.period_start)}</span><strong>{formatCurrency(dashboard.monthly_expenses)}</strong></div>
          <div><span>Contas acompanhadas</span><strong>{accounts.length}</strong></div>
        </div>
        {accounts.length > 0 && <section className="context-cards"><div className="context-section-heading"><span>Saldos por conta</span></div>{accounts.slice(0, 4).map((account) => <div className="context-card-row" key={account.id}><span>{account.name}</span><strong>{account.balance === null ? "Pendente" : formatCurrency(account.balance)}</strong></div>)}</section>}
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

function SettingsView({
  loading,
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
  const [assistantPreferences, setAssistantPreferences] = useState(DEFAULT_ASSISTANT_PREFERENCES);
  const [savingAssistantPreferences, setSavingAssistantPreferences] = useState(false);
  const [assistantPreferencesError, setAssistantPreferencesError] = useState("");
  const [assistantPreferencesSaved, setAssistantPreferencesSaved] = useState(false);
  const [memoryDraft, setMemoryDraft] = useState("");
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [savingMemory, setSavingMemory] = useState(false);
  const [memoryError, setMemoryError] = useState("");

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
            <form className="settings-memory-form" onSubmit={(event) => void submitMemory(event)}>
              <label className="settings-memory-label" htmlFor="assistant-preference">Lembrete para a SophIA</label>
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
            {visibleMemories.length === 0 ? <div className="settings-memory-empty">Nenhum lembrete adicional. As escolhas estruturadas ficam em “Meu Assistente”.</div> : visibleMemories.map((memory) => <div className="settings-memory-row" key={memory.id}><span>{memory.content}</span><div><button aria-label={`Editar preferência: ${memory.content}`} onClick={() => editMemory(memory)} type="button">Editar</button><button aria-label={`Remover preferência: ${memory.content}`} onClick={() => onDeleteMemory(memory.id)} type="button">Remover</button></div></div>)}
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
                  {diagnostics.map((item) => (
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
                      {item.error_summary && <p className="settings-diagnostic-error">{item.error_summary}</p>}
                    </article>
                  ))}
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </section>
  );
}
