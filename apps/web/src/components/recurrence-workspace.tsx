"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { CalendarClock, Check, CircleOff, Pencil, Plus, Repeat2, X } from "lucide-react";

import { ApiError, apiRequest } from "@/lib/api";
import { formatCurrency, toDecimalString } from "@/lib/money";
import { CurrencyInput } from "@/components/currency-input";
import { HelpTip } from "@/components/help-tip";
import { CalendarDateInput } from "@/components/calendar-date-input";
import { BrandMark } from "@/components/brand-mark";

type MovementType = "INCOME" | "EXPENSE";
type Frequency = "DAILY" | "WEEKLY" | "MONTHLY" | "YEARLY";
type OccurrenceStatus = "PLANNED" | "PENDING" | "OVERDUE" | "PAID" | "SKIPPED" | "CANCELLED";
type Scope = "THIS" | "THIS_AND_FUTURE" | "ENTIRE_RULE";

type Account = { id: string; name: string; is_active: boolean };
type Category = { id: string; name: string; type: MovementType; is_archived: boolean };
type RecurrenceRule = {
  id: string;
  account_id: string;
  category_id: string;
  type: MovementType;
  description: string;
  amount: string;
  frequency: Frequency;
  interval: number;
  starts_on: string;
  ends_on: string | null;
  notes: string | null;
  is_active: boolean;
};
type RecurrenceOccurrence = {
  id: string;
  rule_id: string;
  transaction_id: string | null;
  account_id: string;
  category_id: string;
  type: MovementType;
  description: string;
  amount: string;
  due_date: string;
  notes: string | null;
  status: OccurrenceStatus;
};
type RuleForm = {
  account_id: string;
  category_id: string;
  type: MovementType;
  description: string;
  amount: string;
  frequency: Frequency;
  interval: string;
  starts_on: string;
  ends_on: string;
  notes: string;
};
type OccurrenceForm = { description: string; amount: string; notes: string; scope: Scope };
type Notice = { kind: "success" | "error"; message: string } | null;

function financialDate(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "America/Sao_Paulo",
    year: "numeric",
  }).formatToParts(new Date());
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function displayDate(value: string): string {
  const [year, month, day] = value.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

function emptyRule(): RuleForm {
  return {
    account_id: "",
    category_id: "",
    type: "EXPENSE",
    description: "",
    amount: "",
    frequency: "MONTHLY",
    interval: "1",
    starts_on: financialDate(),
    ends_on: "",
    notes: "",
  };
}

function frequencyLabel(frequency: Frequency, interval: number): string {
  const labels: Record<Frequency, [string, string]> = {
    DAILY: ["dia", "dias"],
    WEEKLY: ["semana", "semanas"],
    MONTHLY: ["mês", "meses"],
    YEARLY: ["ano", "anos"],
  };
  const [singular, plural] = labels[frequency];
  return interval === 1 ? `A cada ${singular}` : `A cada ${interval} ${plural}`;
}

function statusLabel(status: OccurrenceStatus): string {
  const labels: Record<OccurrenceStatus, string> = {
    PLANNED: "Previsto",
    PENDING: "Para hoje",
    OVERDUE: "Em atraso",
    PAID: "Registrado",
    SKIPPED: "Ignorado",
    CANCELLED: "Cancelado",
  };
  return labels[status];
}

export function RecurrenceWorkspace() {
  const [rules, setRules] = useState<RecurrenceRule[]>([]);
  const [occurrences, setOccurrences] = useState<RecurrenceOccurrence[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [ruleFormOpen, setRuleFormOpen] = useState(false);
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);
  const [ruleForm, setRuleForm] = useState<RuleForm>(emptyRule);
  const [editingOccurrence, setEditingOccurrence] = useState<RecurrenceOccurrence | null>(null);
  const [occurrenceForm, setOccurrenceForm] = useState<OccurrenceForm>({
    description: "",
    amount: "",
    notes: "",
    scope: "THIS",
  });
  const [showHistory, setShowHistory] = useState(false);

  const loadData = useCallback(async (showLoader = true) => {
    if (showLoader) setLoading(true);
    try {
      const [ruleRows, occurrenceRows, accountRows, categoryRows] = await Promise.all([
        apiRequest<RecurrenceRule[]>("/api/recurrences"),
        apiRequest<RecurrenceOccurrence[]>("/api/recurrences/occurrences"),
        apiRequest<Account[]>("/api/accounts?include_archived=true"),
        apiRequest<Category[]>("/api/categories?include_archived=true"),
      ]);
      setRules(ruleRows);
      setOccurrences(occurrenceRows);
      setAccounts(accountRows);
      setCategories(categoryRows);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        window.location.reload();
        return;
      }
      setNotice({
        kind: "error",
        message: error instanceof Error ? error.message : "Não foi possível carregar as recorrências.",
      });
    } finally {
      if (showLoader) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const activeAccounts = accounts.filter((account) => account.is_active);
  const currentCategories = categories.filter(
    (category) => !category.is_archived && category.type === ruleForm.type,
  );
  const visibleOccurrences = occurrences
    .filter((item) => showHistory || !["PAID", "SKIPPED", "CANCELLED"].includes(item.status))
    .slice(0, showHistory ? 60 : 18);

  function openNewRule() {
    setEditingRuleId(null);
    const expenseCategory = categories.find(
      (category) => !category.is_archived && category.type === "EXPENSE",
    );
    setRuleForm({
      ...emptyRule(),
      account_id: activeAccounts[0]?.id ?? "",
      category_id: expenseCategory?.id ?? "",
    });
    setRuleFormOpen(true);
    setNotice(null);
  }

  function openRuleEdit(rule: RecurrenceRule) {
    setEditingRuleId(rule.id);
    setRuleForm({
      account_id: rule.account_id,
      category_id: rule.category_id,
      type: rule.type,
      description: rule.description,
      amount: rule.amount.replace(".", ","),
      frequency: rule.frequency,
      interval: String(rule.interval),
      starts_on: rule.starts_on,
      ends_on: rule.ends_on ?? "",
      notes: rule.notes ?? "",
    });
    setRuleFormOpen(true);
    setNotice(null);
  }

  async function saveRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNotice(null);
    try {
      const payload = {
        ...ruleForm,
        amount: toDecimalString(ruleForm.amount),
        interval: Number(ruleForm.interval),
        ends_on: ruleForm.ends_on || null,
        notes: ruleForm.notes.trim() || null,
      };
      const path = editingRuleId ? `/api/recurrences/${editingRuleId}` : "/api/recurrences";
      await apiRequest<RecurrenceRule>(path, {
        method: editingRuleId ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      });
      setRuleFormOpen(false);
      setEditingRuleId(null);
      setNotice({ kind: "success", message: editingRuleId ? "Recorrência atualizada." : "Recorrência criada." });
      await loadData(false);
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível salvar." });
    } finally {
      setBusy(false);
    }
  }

  async function cancelRule(rule: RecurrenceRule) {
    if (!window.confirm(`Encerrar a recorrência “${rule.description}”?`)) return;
    setBusy(true);
    setNotice(null);
    try {
      await apiRequest<RecurrenceRule>(`/api/recurrences/${rule.id}/cancel`, { method: "POST" });
      setNotice({ kind: "success", message: "Recorrência encerrada. O histórico foi preservado." });
      await loadData(false);
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível encerrar." });
    } finally {
      setBusy(false);
    }
  }

  async function changeOccurrence(occurrence: RecurrenceOccurrence, action: "pay" | "skip") {
    setBusy(true);
    setNotice(null);
    try {
      const result = await apiRequest<RecurrenceOccurrence>(
        `/api/recurrences/${occurrence.rule_id}/occurrences/${occurrence.id}/${action}`,
        { method: "POST" },
      );
      setNotice({
        kind: "success",
        message: action === "pay" ? "Pagamento registrado nos lançamentos de hoje." : "Ocorrência ignorada.",
      });
      setOccurrences((rows) => rows.map((row) => (row.id === result.id ? result : row)));
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível atualizar." });
    } finally {
      setBusy(false);
    }
  }

  function openOccurrenceEdit(occurrence: RecurrenceOccurrence) {
    setEditingOccurrence(occurrence);
    setOccurrenceForm({
      description: occurrence.description,
      amount: occurrence.amount.replace(".", ","),
      notes: occurrence.notes ?? "",
      scope: "THIS",
    });
    setNotice(null);
  }

  async function saveOccurrence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingOccurrence) return;
    setBusy(true);
    setNotice(null);
    try {
      const updated = await apiRequest<RecurrenceOccurrence>(
        `/api/recurrences/${editingOccurrence.rule_id}/occurrences/${editingOccurrence.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            ...occurrenceForm,
            amount: toDecimalString(occurrenceForm.amount),
            notes: occurrenceForm.notes.trim() || null,
          }),
        },
      );
      setOccurrences((rows) => rows.map((row) => {
        if (row.id === updated.id) return updated;
        if (occurrenceForm.scope !== "THIS" && row.rule_id === updated.rule_id && row.due_date >= updated.due_date) {
          return { ...row, description: updated.description, amount: updated.amount, notes: updated.notes };
        }
        return row;
      }));
      setEditingOccurrence(null);
      setNotice({ kind: "success", message: "Ocorrência atualizada." });
      await loadData(false);
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível editar." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="recurrence-workspace">
      <div className="recurrence-intro">
        <span className="recurrence-intro-mark"><Repeat2 aria-hidden="true" size={18} /></span>
        <p>Uma regra prevê as próximas datas e valores. Elas aparecem como ocorrências abaixo; seu saldo só muda quando você registra o pagamento ou recebimento.</p>
      </div>

      {notice && (
        <div className={`workspace-notice ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
          {notice.message}
          <button aria-label="Fechar aviso" onClick={() => setNotice(null)} type="button"><X size={15} /></button>
        </div>
      )}

      {ruleFormOpen && (
        <form className="editor-form recurrence-form" onSubmit={saveRule}>
          <div className="editor-heading">
            <div><p className="eyebrow">Programação financeira</p><h3>{editingRuleId ? "Editar recorrência" : "Nova recorrência"}</h3></div>
            <button aria-label="Fechar formulário" className="text-button" onClick={() => setRuleFormOpen(false)} type="button"><X size={17} /></button>
          </div>
          <div className="form-grid recurrence-form-grid">
            <label className="field-label">Descrição<input maxLength={200} onChange={(event) => setRuleForm({ ...ruleForm, description: event.target.value })} required value={ruleForm.description} /></label>
            <label className="field-label">Tipo<select onChange={(event) => setRuleForm({ ...ruleForm, type: event.target.value as MovementType, category_id: "" })} value={ruleForm.type}><option value="EXPENSE">Despesa</option><option value="INCOME">Receita</option></select></label>
            <div className="field-label"><label htmlFor="recurrence-amount">Valor</label><CurrencyInput id="recurrence-amount" onChange={(value) => setRuleForm({ ...ruleForm, amount: value })} placeholder="0,00" required value={ruleForm.amount} /></div>
            <label className="field-label">Conta<select onChange={(event) => setRuleForm({ ...ruleForm, account_id: event.target.value })} required value={ruleForm.account_id}><option value="">Selecione</option>{activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select><small>Conta que será afetada quando você registrar a ocorrência.</small></label>
            <label className="field-label">Categoria<select onChange={(event) => setRuleForm({ ...ruleForm, category_id: event.target.value })} required value={ruleForm.category_id}><option value="">Selecione</option>{currentCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select><small>Classificação do lançamento criado ao registrar o pagamento ou recebimento.</small></label>
            <label className="field-label"><span className="field-label-heading">Frequência <HelpTip label="Frequência">Escolha a unidade usada para repetir este compromisso: dia, semana, mês ou ano.</HelpTip></span><select onChange={(event) => setRuleForm({ ...ruleForm, frequency: event.target.value as Frequency })} value={ruleForm.frequency}><option value="DAILY">Diária</option><option value="WEEKLY">Semanal</option><option value="MONTHLY">Mensal</option><option value="YEARLY">Anual</option></select><small>Exemplo: Mensal significa uma previsão por mês.</small></label>
            <label className="field-label"><span className="field-label-heading">Repetir a cada <HelpTip label="Intervalo da repetição">Usa a frequência escolhida ao lado. Ex.: Mensal + 1 mês repete todo mês; 2 meses cria uma previsão a cada dois meses.</HelpTip></span><span className="recurrence-interval-field"><input max="365" min="1" onChange={(event) => setRuleForm({ ...ruleForm, interval: event.target.value })} required type="number" value={ruleForm.interval} /><span>{frequencyUnit(ruleForm.frequency)}</span></span></label>
            <div className="field-label"><span className="field-label-heading"><label htmlFor="recurrence-start-date">Começa em</label><HelpTip label="Data de início">A primeira data em que esta regra pode gerar uma ocorrência prevista.</HelpTip></span><CalendarDateInput id="recurrence-start-date" onChange={(value) => setRuleForm({ ...ruleForm, starts_on: value })} required value={ruleForm.starts_on} /></div>
            <div className="field-label"><span className="field-label-heading"><label htmlFor="recurrence-end-date">Termina em (opcional)</label><HelpTip label="Data final">Depois desta data, a regra não gera novas ocorrências. Deixe em branco para manter a regra ativa até você encerrá-la.</HelpTip></span><CalendarDateInput id="recurrence-end-date" onChange={(value) => setRuleForm({ ...ruleForm, ends_on: value })} value={ruleForm.ends_on} /></div>
            <label className="field-label recurrence-notes">Observações<textarea maxLength={2000} onChange={(event) => setRuleForm({ ...ruleForm, notes: event.target.value })} rows={2} value={ruleForm.notes} /><small>Detalhes que também aparecerão no lançamento quando você registrar uma ocorrência.</small></label>
          </div>
          {(activeAccounts.length === 0 || currentCategories.length === 0) && <p className="form-note">Cadastre uma conta ativa e uma categoria do tipo escolhido antes de criar a recorrência.</p>}
          <div className="recurrence-form-actions"><button className="secondary-button compact-button" onClick={() => setRuleFormOpen(false)} type="button">Cancelar</button><button className="primary-button compact-button" disabled={busy || activeAccounts.length === 0 || currentCategories.length === 0} type="submit">{busy ? "Salvando…" : "Salvar recorrência"}</button></div>
        </form>
      )}

      {editingOccurrence && (
        <form className="editor-form recurrence-form" onSubmit={saveOccurrence}>
          <div className="editor-heading"><div><p className="eyebrow">{displayDate(editingOccurrence.due_date)}</p><h3>Editar ocorrência</h3></div><button aria-label="Fechar edição" className="text-button" onClick={() => setEditingOccurrence(null)} type="button"><X size={17} /></button></div>
          <div className="form-grid recurrence-edit-grid">
            <label className="field-label">Descrição<input maxLength={200} onChange={(event) => setOccurrenceForm({ ...occurrenceForm, description: event.target.value })} required value={occurrenceForm.description} /></label>
            <div className="field-label"><label htmlFor="occurrence-amount">Valor</label><CurrencyInput id="occurrence-amount" onChange={(value) => setOccurrenceForm({ ...occurrenceForm, amount: value })} placeholder="0,00" required value={occurrenceForm.amount} /></div>
            <label className="field-label">Alterar<select onChange={(event) => setOccurrenceForm({ ...occurrenceForm, scope: event.target.value as Scope })} value={occurrenceForm.scope}><option value="THIS">Só esta ocorrência</option><option value="THIS_AND_FUTURE">Esta e as próximas</option><option value="ENTIRE_RULE">Toda a regra futura</option></select></label>
            <label className="field-label">Observações<input maxLength={2000} onChange={(event) => setOccurrenceForm({ ...occurrenceForm, notes: event.target.value })} value={occurrenceForm.notes} /></label>
          </div>
          <div className="recurrence-form-actions"><button className="secondary-button compact-button" onClick={() => setEditingOccurrence(null)} type="button">Cancelar</button><button className="primary-button compact-button" disabled={busy} type="submit">{busy ? "Salvando…" : "Salvar alteração"}</button></div>
        </form>
      )}

      {loading ? (
        <div className="finance-loading" role="status"><BrandMark className="loading-mark" size={30} />Carregando recorrências…</div>
      ) : (
        <>
          <section className="surface-card data-card recurrence-rules-card">
            <div className="surface-heading">
              <div><p className="eyebrow">Regras ativas</p><h2>O que se repete</h2></div>
              <button className="primary-button compact-button" onClick={openNewRule} type="button"><Plus aria-hidden="true" size={16} /> Nova recorrência</button>
            </div>
            {rules.length === 0 ? (
              <div className="recurrence-empty"><CalendarClock aria-hidden="true" size={22} /><div><strong>Nada programado por enquanto</strong><p>Cadastre uma despesa ou receita que se repete, como aluguel, salário ou assinatura.</p></div></div>
            ) : (
              <div className="recurrence-rule-list">
                {rules.map((rule) => {
                  const account = accounts.find((item) => item.id === rule.account_id)?.name ?? "Conta arquivada";
                  const category = categories.find((item) => item.id === rule.category_id)?.name ?? "Categoria arquivada";
                  return (
                    <article className="recurrence-rule-row" key={rule.id}>
                      <span className={`recurrence-kind-mark ${rule.type === "INCOME" ? "income" : "expense"}`} aria-hidden="true">{rule.type === "INCOME" ? "+" : "−"}</span>
                      <div className="recurrence-rule-main"><strong>{rule.description}</strong><span>{account} · {category} · {frequencyLabel(rule.frequency, rule.interval)}</span><small>Desde {displayDate(rule.starts_on)}{rule.ends_on ? ` · até ${displayDate(rule.ends_on)}` : " · sem data final"}</small></div>
                      <strong className="recurrence-amount">{formatCurrency(rule.amount)}</strong>
                      <div className="recurrence-actions"><button aria-label={`Editar ${rule.description}`} className="table-action" disabled={busy} onClick={() => openRuleEdit(rule)} type="button"><Pencil size={15} /><span>Editar</span></button><button className="table-action danger-action" disabled={busy} onClick={() => void cancelRule(rule)} type="button"><CircleOff size={15} /><span>Encerrar</span></button></div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <section className="surface-card data-card recurrence-occurrences-card">
            <div className="surface-heading">
              <div><p className="eyebrow">Próximos 90 dias</p><h2>Ocorrências <HelpTip label="Ocorrências programadas">Cada ocorrência é uma data e um valor previstos pela regra acima. Ainda não afeta o saldo. Ao marcar como pago ou recebido, a SophIA cria um único lançamento com a data de hoje.</HelpTip></h2></div>
              <label className="recurrence-history-toggle"><input checked={showHistory} onChange={(event) => setShowHistory(event.target.checked)} type="checkbox" /> Mostrar histórico</label>
            </div>
            {visibleOccurrences.length === 0 ? (
              <div className="recurrence-empty"><CalendarClock aria-hidden="true" size={22} /><div><strong>Nenhuma ocorrência no período</strong><p>Quando você criar uma regra, as datas previstas aparecerão aqui.</p></div></div>
            ) : (
              <div className="recurrence-occurrence-list">
                {visibleOccurrences.map((item) => {
                  const account = accounts.find((row) => row.id === item.account_id)?.name ?? "Conta arquivada";
                  const canAct = ["PLANNED", "PENDING", "OVERDUE"].includes(item.status);
                  return (
                    <article className="recurrence-occurrence-row" key={item.id}>
                      <time className="recurrence-date" dateTime={item.due_date}>{displayDate(item.due_date)}</time>
                      <div className="recurrence-occurrence-main"><strong>{item.description}</strong><span>{account}{item.type === "INCOME" ? " · Receita" : " · Despesa"}</span></div>
                      <strong className={`recurrence-amount ${item.type === "INCOME" ? "income" : "expense"}`}>{item.type === "INCOME" ? "+" : "−"}{formatCurrency(item.amount)}</strong>
                      <span className={`recurrence-status ${item.status.toLowerCase()}`}>{statusLabel(item.status)}</span>
                      {canAct && <div className="recurrence-actions"><button className="table-action" disabled={busy} onClick={() => openOccurrenceEdit(item)} type="button"><Pencil size={15} /><span>Editar</span></button><button className="table-action" disabled={busy} onClick={() => void changeOccurrence(item, "pay")} type="button"><Check size={15} /><span>{item.type === "INCOME" ? "Marcar como recebido" : "Marcar como pago"}</span></button><button aria-label={`Ignorar ${item.description}`} className="table-action danger-action" disabled={busy} onClick={() => void changeOccurrence(item, "skip")} type="button">Ignorar</button></div>}
                    </article>
                  );
                })}
              </div>
            )}
            {visibleOccurrences.length >= (showHistory ? 60 : 18) && <p className="recurrence-list-limit">A lista mostra até {showHistory ? "60" : "18"} itens para manter a navegação rápida.</p>}
          </section>
        </>
      )}
    </div>
  );
}

function frequencyUnit(frequency: Frequency): string {
  const units: Record<Frequency, string> = {
    DAILY: "dia(s)",
    WEEKLY: "semana(s)",
    MONTHLY: "mês(es)",
    YEARLY: "ano(s)",
  };
  return units[frequency];
}
