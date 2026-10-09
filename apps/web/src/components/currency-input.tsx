"use client";

import { useState, type FocusEvent, type InputHTMLAttributes } from "react";

import { formatCurrencyInput, formatCurrencyInputForEditing } from "@/lib/money";

type CurrencyInputProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "type" | "inputMode" | "value" | "onChange"
> & {
  value: string;
  onChange: (value: string) => void;
};

export function CurrencyInput({
  onBlur,
  onChange,
  onFocus,
  value,
  ...inputProps
}: CurrencyInputProps) {
  const [isFocused, setIsFocused] = useState(false);
  const [draft, setDraft] = useState("");

  function handleBlur(event: FocusEvent<HTMLInputElement>) {
    const formatted = formatCurrencyInput(event.currentTarget.value);
    setDraft(formatted);
    setIsFocused(false);
    onChange(formatted);
    onBlur?.(event);
  }

  return (
    <span className="currency-input">
      <span aria-hidden="true" className="currency-input-prefix">R$</span>
      <input
        {...inputProps}
        autoComplete={inputProps.autoComplete ?? "off"}
        inputMode="decimal"
        onBlur={handleBlur}
        onChange={(event) => {
          setDraft(event.currentTarget.value);
          onChange(event.currentTarget.value);
        }}
        onFocus={(event) => {
          setDraft(formatCurrencyInputForEditing(value));
          setIsFocused(true);
          onFocus?.(event);
        }}
        type="text"
        value={isFocused ? draft : formatCurrencyInput(value)}
      />
    </span>
  );
}
