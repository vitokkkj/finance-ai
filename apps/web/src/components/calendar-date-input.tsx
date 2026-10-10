"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";

type CalendarDateInputProps = {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  disabled?: boolean;
  "aria-label"?: string;
};

const WEEKDAYS = [
  { label: "D", fullName: "Domingo" },
  { label: "S", fullName: "Segunda-feira" },
  { label: "T", fullName: "Terça-feira" },
  { label: "Q", fullName: "Quarta-feira" },
  { label: "Q", fullName: "Quinta-feira" },
  { label: "S", fullName: "Sexta-feira" },
  { label: "S", fullName: "Sábado" },
];

function parseIso(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day
    ? parsed
    : null;
}

function parseBrazilian(value: string): string | null {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value.trim());
  if (!match) return null;
  const parsed = parseIso(`${match[3]}-${match[2]}-${match[1]}`);
  return parsed ? `${match[3]}-${match[2]}-${match[1]}` : null;
}

function displayBrazilian(value: string): string {
  const parsed = parseIso(value);
  if (!parsed) return "";
  return `${String(parsed.getUTCDate()).padStart(2, "0")}/${String(parsed.getUTCMonth() + 1).padStart(2, "0")}/${parsed.getUTCFullYear()}`;
}

function todayInSaoPaulo(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "America/Sao_Paulo",
    year: "numeric",
  }).formatToParts(new Date());
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function monthLabel(year: number, month: number): string {
  return new Intl.DateTimeFormat("pt-BR", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month, 1, 12)));
}

export function CalendarDateInput({
  id,
  value,
  onChange,
  required = false,
  disabled = false,
  "aria-label": ariaLabel,
}: CalendarDateInputProps) {
  const today = todayInSaoPaulo();
  const selected = parseIso(value);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(displayBrazilian(value));
  const [visibleMonth, setVisibleMonth] = useState(() => {
    const initial = selected ?? parseIso(today);
    return { year: initial?.getUTCFullYear() ?? 2026, month: initial?.getUTCMonth() ?? 0 };
  });
  const rootRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    setDraft(displayBrazilian(value));
  }, [value]);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) setOpen(false);
    };
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  function showCalendar() {
    const monthDate = selected ?? parseIso(today);
    if (monthDate) setVisibleMonth({ year: monthDate.getUTCFullYear(), month: monthDate.getUTCMonth() });
    setOpen(true);
  }

  function moveMonth(offset: number) {
    const next = new Date(Date.UTC(visibleMonth.year, visibleMonth.month + offset, 1));
    setVisibleMonth({ year: next.getUTCFullYear(), month: next.getUTCMonth() });
  }

  function changeDraft(nextDraft: string) {
    setDraft(nextDraft);
    if (!nextDraft.trim()) onChange("");
    else {
      const parsed = parseBrazilian(nextDraft);
      if (parsed) onChange(parsed);
    }
  }

  function handleInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      showCalendar();
    }
  }

  const firstWeekday = new Date(Date.UTC(visibleMonth.year, visibleMonth.month, 1)).getUTCDay();
  const dayCount = new Date(Date.UTC(visibleMonth.year, visibleMonth.month + 1, 0)).getUTCDate();
  const days = Array.from({ length: dayCount }, (_, index) => index + 1);
  const blankCells = Array.from(
    { length: firstWeekday },
    (_, index) => `${visibleMonth.year}-${visibleMonth.month}-blank-${index}`,
  );
  const calendarId = id ? `${id}-calendar` : undefined;

  return (
    <span className="sophia-date-input" ref={rootRef}>
      <input
        aria-label={ariaLabel}
        autoComplete="off"
        disabled={disabled}
        id={id}
        inputMode="numeric"
        maxLength={10}
        onBlur={() => {
          if (!draft.trim()) return;
          const parsed = parseBrazilian(draft);
          setDraft(parsed ? displayBrazilian(parsed) : displayBrazilian(value));
        }}
        onChange={(event) => changeDraft(event.currentTarget.value)}
        onKeyDown={handleInputKeyDown}
        pattern="\\d{2}/\\d{2}/\\d{4}"
        placeholder="dd/mm/aaaa"
        required={required}
        type="text"
        value={draft}
      />
      <button
        aria-label={open ? "Fechar calendário" : "Abrir calendário"}
        aria-controls={calendarId}
        aria-expanded={open}
        className="sophia-date-trigger"
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : showCalendar())}
        type="button"
      >
        <CalendarDays aria-hidden="true" size={17} strokeWidth={1.8} />
      </button>
      {open && (
        <dialog className="sophia-calendar-popover" id={calendarId} open aria-label="Escolher data">
          <span className="sophia-calendar-heading">
            <button aria-label="Mês anterior" onClick={() => moveMonth(-1)} type="button"><ChevronLeft aria-hidden="true" size={17} /></button>
            <strong>{monthLabel(visibleMonth.year, visibleMonth.month)}</strong>
            <button aria-label="Próximo mês" onClick={() => moveMonth(1)} type="button"><ChevronRight aria-hidden="true" size={17} /></button>
          </span>
          <div className="sophia-calendar-grid">
            {WEEKDAYS.map(({ label, fullName }) => <abbr className="sophia-calendar-weekday" key={fullName} title={fullName}>{label}</abbr>)}
            {blankCells.map((key) => <span aria-hidden="true" className="sophia-calendar-blank" key={key} />)}
            {days.map((day) => {
              const dayIso = `${visibleMonth.year}-${String(visibleMonth.month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
              const isSelected = dayIso === value;
              const isToday = dayIso === today;
              return (
                <button
                  aria-current={isToday ? "date" : undefined}
                  aria-label={`${day} de ${monthLabel(visibleMonth.year, visibleMonth.month)}`}
                  aria-pressed={isSelected}
                  className={`${isSelected ? "selected " : ""}${isToday ? "today" : ""}`.trim()}
                  key={dayIso}
                  onClick={() => {
                    onChange(dayIso);
                    setDraft(displayBrazilian(dayIso));
                    setOpen(false);
                  }}
                  type="button"
                >{day}</button>
              );
            })}
          </div>
          <button className="sophia-calendar-today" onClick={() => { onChange(today); setDraft(displayBrazilian(today)); setOpen(false); }} type="button">Hoje</button>
        </dialog>
      )}
    </span>
  );
}
