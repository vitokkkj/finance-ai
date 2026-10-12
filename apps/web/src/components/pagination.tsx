"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

export const PAGE_SIZE = 15;

export function usePagination<T>(items: T[], resetKey = "", pageSize = PAGE_SIZE) {
  const [requestedPage, setRequestedPage] = useState(1);
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const page = Math.min(requestedPage, pageCount);
  const startIndex = items.length === 0 ? 0 : (page - 1) * pageSize;
  const pageItems = items.slice(startIndex, startIndex + pageSize);

  // biome-ignore lint/correctness/useExhaustiveDependencies: A change in the caller's reset key returns the list to page one.
  useEffect(() => {
    setRequestedPage(1);
  }, [resetKey]);

  useEffect(() => {
    if (requestedPage !== page) setRequestedPage(page);
  }, [page, requestedPage]);

  return {
    items: pageItems,
    page,
    pageCount,
    pageSize,
    start: startIndex + 1,
    end: startIndex + pageItems.length,
    total: items.length,
    setPage: setRequestedPage,
  };
}

export function PaginationControls({
  page,
  pageCount,
  start,
  end,
  total,
  onPageChange,
  label,
}: {
  page: number;
  pageCount: number;
  start: number;
  end: number;
  total: number;
  onPageChange: (page: number) => void;
  label: string;
}) {
  if (total <= PAGE_SIZE) return null;

  return (
    <nav aria-label={label} className="pagination-controls">
      <span aria-live="polite">Mostrando {start}–{end} de {total}</span>
      <div className="pagination-controls-actions">
        <button disabled={page <= 1} onClick={() => onPageChange(page - 1)} type="button">
          <ChevronLeft aria-hidden="true" size={15} /> Anterior
        </button>
        <span>Página {page} de {pageCount}</span>
        <button disabled={page >= pageCount} onClick={() => onPageChange(page + 1)} type="button">
          Próxima <ChevronRight aria-hidden="true" size={15} />
        </button>
      </div>
    </nav>
  );
}
