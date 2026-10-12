"use client";

import { useRef, useState, type ChangeEvent } from "react";
import { AlertTriangle, FileCheck2, FileUp, RotateCcw } from "lucide-react";

import { ApiError, apiRequest } from "@/lib/api";
import { formatCurrency } from "@/lib/money";
import { PaginationControls, usePagination } from "@/components/pagination";

type ImportMatch = {
  kind: "exact" | "similar";
  source: "transaction" | "csv_row";
  transaction_id: string | null;
  row_number: number | null;
  description: string;
  occurred_at: string;
  amount: string;
};

type ImportRow = {
  row_number: number;
  occurred_at: string;
  description: string;
  type: "INCOME" | "EXPENSE";
  amount: string;
  account_name: string;
  category_name: string;
  matches: ImportMatch[];
  matches_truncated: boolean;
};

type Preview = {
  preview_token: string;
  expires_at: string;
  row_count: number;
  rows: ImportRow[];
};

type ImportResult = { imported_count: number; skipped_count: number };
type Decision = "IMPORT" | "SKIP";

const MAX_FILE_BYTES = 1_000_000;

function formatImportDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

export function TransactionImport({ onImported }: { onImported: (message: string) => Promise<void> }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [csvContent, setCsvContent] = useState("");
  const [fileName, setFileName] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [decisions, setDecisions] = useState<Record<number, Decision>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: "success" | "error"; message: string } | null>(null);
  const previewPagination = usePagination(preview?.rows ?? [], preview?.preview_token ?? "");

  const reset = () => {
    setCsvContent("");
    setFileName("");
    setPreview(null);
    setDecisions({});
    setConfirmed(false);
    setNotice(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const chooseFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setPreview(null);
    setDecisions({});
    setConfirmed(false);
    setNotice(null);
    if (!file) return;
    if (!file.name.toLocaleLowerCase("pt-BR").endsWith(".csv")) {
      setNotice({ kind: "error", message: "Escolha um arquivo CSV." });
      event.target.value = "";
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setNotice({ kind: "error", message: "O CSV pode ter no máximo 1 MB." });
      event.target.value = "";
      return;
    }
    try {
      const content = await file.text();
      setCsvContent(content);
      setFileName(file.name);
    } catch {
      setNotice({ kind: "error", message: "Não foi possível ler o arquivo. Tente selecioná-lo novamente." });
      event.target.value = "";
    }
  };

  const createPreview = async () => {
    setBusy(true);
    setNotice(null);
    try {
      const result = await apiRequest<Preview>("/api/imports/transactions/preview", {
        method: "POST",
        body: JSON.stringify({ csv_content: csvContent }),
      });
      setPreview(result);
      setDecisions({});
      setConfirmed(false);
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof ApiError ? error.message : "Não foi possível preparar a prévia." });
    } finally {
      setBusy(false);
    }
  };

  const commitImport = async () => {
    if (!preview || !confirmed) return;
    setBusy(true);
    setNotice(null);
    try {
      const result = await apiRequest<ImportResult>("/api/imports/transactions/confirm", {
        method: "POST",
        body: JSON.stringify({
          csv_content: csvContent,
          preview_token: preview.preview_token,
          confirmed: true,
          decisions: Object.entries(decisions).map(([rowNumber, action]) => ({ row_number: Number(rowNumber), action })),
        }),
      });
      const successMessage = `${result.imported_count} ${result.imported_count === 1 ? "lançamento importado" : "lançamentos importados"}; ${result.skipped_count} ${result.skipped_count === 1 ? "linha ignorada" : "linhas ignoradas"}.`;
      setNotice(null);
      setPreview(null);
      setCsvContent("");
      setFileName("");
      setDecisions({});
      setConfirmed(false);
      if (inputRef.current) inputRef.current.value = "";
      await onImported(successMessage);
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof ApiError ? error.message : "Não foi possível concluir a importação." });
    } finally {
      setBusy(false);
    }
  };

  const rowsToImport = preview?.rows.filter((row) => !row.matches.length || decisions[row.row_number] === "IMPORT").length ?? 0;
  const hasUnresolved = preview?.rows.some((row) => row.matches.length > 0 && !decisions[row.row_number]) ?? false;

  return (
    <section aria-labelledby="transaction-import-title" className="transaction-import-card">
      <div className="transaction-import-heading">
        <div className="transaction-import-icon" aria-hidden="true"><FileUp size={17} /></div>
        <div><p className="eyebrow">Importação revisável</p><h3 id="transaction-import-title">Importar lançamentos por CSV</h3></div>
      </div>
      <p className="transaction-import-copy">A SophIA confere o arquivo e sugere possíveis duplicidades. Nada é gravado até você revisar e confirmar.</p>
      <div className="transaction-import-actions">
        <input accept=".csv,text/csv" aria-label="Arquivo CSV" className="sr-only" onChange={(event) => void chooseFile(event)} ref={inputRef} type="file" />
        <button aria-label={fileName || "Escolher CSV"} className="secondary-button compact-button transaction-import-file-button" disabled={busy || Boolean(preview)} onClick={() => inputRef.current?.click()} type="button">{fileName || "Escolher CSV"}</button>
        {preview ? (
          <button className="text-button transaction-import-reset" disabled={busy} onClick={reset} type="button"><RotateCcw size={13} /> Trocar arquivo</button>
        ) : (
          <button className="primary-button compact-button" disabled={busy || !csvContent} onClick={() => void createPreview()} type="button">{busy ? "Analisando…" : "Analisar arquivo"}</button>
        )}
      </div>
      <p className="transaction-import-hint">CSV UTF-8 de até 1 MB. <a download href="/modelo-importacao-lancamentos.csv">Baixar modelo de arquivo</a></p>
      {notice && <p className={`transaction-import-notice ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.message}</p>}
      {preview && notice?.kind === "error" && <button className="text-button transaction-import-reset" disabled={busy} onClick={() => void createPreview()} type="button"><RotateCcw size={13} /> Atualizar prévia</button>}
      {preview && (
        <div className="transaction-import-review">
          <div className="transaction-import-review-title"><FileCheck2 aria-hidden="true" size={15} /><strong>Prévia: {preview.row_count} {preview.row_count === 1 ? "linha" : "linhas"}</strong><span>Expira em 15 minutos</span></div>
          <div className="transaction-import-rows">
            {previewPagination.items.map((row) => (
              <article className="transaction-import-row" key={row.row_number}>
                <div className="transaction-import-row-main">
                  <strong>{row.description}</strong>
                  <span>{formatImportDate(row.occurred_at)} · {row.category_name} · {row.account_name}</span>
                </div>
                <strong className={row.type === "INCOME" ? "income" : "expense"}>{row.type === "INCOME" ? "+" : "−"}{formatCurrency(row.amount)}</strong>
                {row.matches.length > 0 && (
                  <div className="transaction-import-match">
                    <AlertTriangle aria-hidden="true" size={14} />
                    <div><strong>Possível duplicidade</strong>{row.matches.map((match) => <span key={`${match.source}-${match.transaction_id ?? match.row_number}`}>{match.kind === "exact" ? "Correspondência exata" : "Valor, data e conta iguais"}: {match.description} · {formatImportDate(match.occurred_at)} · {formatCurrency(match.amount)}{match.source === "csv_row" ? ` · linha ${match.row_number}` : ""}</span>)}{row.matches_truncated && <span>Há outras correspondências; a prévia resumiu a lista.</span>}</div>
                    <label><span>Decisão para linha {row.row_number}</span><select aria-label={`Decisão para linha ${row.row_number}`} onChange={(event) => setDecisions((current) => ({ ...current, [row.row_number]: event.target.value as Decision }))} value={decisions[row.row_number] ?? ""}><option value="">Escolha uma ação</option><option value="IMPORT">Importar mesmo assim</option><option value="SKIP">Ignorar esta linha</option></select></label>
                  </div>
                )}
              </article>
            ))}
          </div>
          <PaginationControls end={previewPagination.end} label="Paginação das linhas importadas" onPageChange={previewPagination.setPage} page={previewPagination.page} pageCount={previewPagination.pageCount} start={previewPagination.start} total={previewPagination.total} />
          {hasUnresolved && <p className="transaction-import-notice error" role="alert">Escolha o que fazer com cada linha sinalizada antes de continuar.</p>}
          <label className="transaction-import-confirm"><input checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} type="checkbox" /><span>Revisei as linhas. Confirmo registrar {rowsToImport} {rowsToImport === 1 ? "lançamento selecionado" : "lançamentos selecionados"}.</span></label>
          <button className="primary-button compact-button" disabled={busy || !confirmed || hasUnresolved || rowsToImport === 0} onClick={() => void commitImport()} type="button">{busy ? "Importando…" : `Confirmar ${rowsToImport} ${rowsToImport === 1 ? "lançamento" : "lançamentos"}`}</button>
        </div>
      )}
    </section>
  );
}
