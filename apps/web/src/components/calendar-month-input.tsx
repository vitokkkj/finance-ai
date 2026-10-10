"use client";

import { useEffect, useId, useRef, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";

type CalendarMonthInputProps = {
  value: string;
  onChange: (value: string) => void;
  "aria-label"?: string;
};

const MONTHS = Array.from({ length: 12 }, (_, month) =>
  new Intl.DateTimeFormat("pt-BR", { month: "long", timeZone: "UTC" })
    .format(new Date(Date.UTC(2026, month, 15, 12))),
);

function parseMonth(value: string): { year: number; month: number } | null {
  const match = /^(\d{4})-(\d{2})$/.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  return month >= 1 && month <= 12 ? { year, month: month - 1 } : null;
}

function monthValue(year: number, month: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}`;
}

function monthDisplay(value: string): string {
  const parsed = parseMonth(value);
  if (!parsed) return "Selecione o mês";
  return `${MONTHS[parsed.month]} de ${parsed.year}`;
}

export function CalendarMonthInput({ value, onChange, "aria-label": ariaLabel = "Selecionar mês" }: CalendarMonthInputProps) {
  const selectedMonth = parseMonth(value);
  const [open, setOpen] = useState(false);
  const [visibleYear, setVisibleYear] = useState(selectedMonth?.year ?? new Date().getFullYear());
  const rootRef = useRef<HTMLDivElement>(null);
  const popoverId = `${useId()}-month-picker`;

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  function showPicker() {
    setVisibleYear(selectedMonth?.year ?? new Date().getFullYear());
    setOpen((current) => !current);
  }

  return (
    <div className="sophia-month-picker" ref={rootRef}>
      <button
        aria-label={ariaLabel}
        aria-controls={popoverId}
        aria-expanded={open}
        className="sophia-month-trigger"
        onClick={showPicker}
        type="button"
      >
        <CalendarDays aria-hidden="true" size={16} strokeWidth={1.8} />
        <span>{monthDisplay(value)}</span>
        <ChevronRight aria-hidden="true" className={open ? "month-trigger-chevron is-open" : "month-trigger-chevron"} size={15} />
      </button>
      {open && (
        <dialog aria-label={ariaLabel} className="sophia-month-popover" id={popoverId} open>
          <div className="sophia-month-heading">
            <button aria-label="Ano anterior" onClick={() => setVisibleYear((year) => year - 1)} type="button"><ChevronLeft aria-hidden="true" size={17} /></button>
            <strong>{visibleYear}</strong>
            <button aria-label="Próximo ano" onClick={() => setVisibleYear((year) => year + 1)} type="button"><ChevronRight aria-hidden="true" size={17} /></button>
          </div>
          <div className="sophia-month-grid">
            {MONTHS.map((month, index) => {
              const optionValue = monthValue(visibleYear, index);
              return (
                <button
                  aria-pressed={optionValue === value}
                  className={optionValue === value ? "selected" : undefined}
                  key={optionValue}
                  onClick={() => { onChange(optionValue); setOpen(false); }}
                  type="button"
                >{month.slice(0, 3)}</button>
              );
            })}
          </div>
        </dialog>
      )}
    </div>
  );
}
