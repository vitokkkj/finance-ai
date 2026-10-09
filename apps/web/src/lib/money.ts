const wholeNumberFormatter = new Intl.NumberFormat("pt-BR", {
  maximumFractionDigits: 0,
  useGrouping: true,
});
const currencyParts = new Intl.NumberFormat("pt-BR", {
  currency: "BRL",
  maximumFractionDigits: 0,
  minimumFractionDigits: 0,
  style: "currency",
}).formatToParts(0);
const currencySymbol = currencyParts.find((part) => part.type === "currency")?.value ?? "R$";
const currencySpacing = currencyParts.find((part) => part.type === "literal")?.value ?? " ";

export function formatCurrency(value: string): string {
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(value);
  if (!match) return "R$ —";

  const [, sign, whole, fraction = ""] = match;
  const groupedWhole = wholeNumberFormatter.format(BigInt(whole));
  const cents = fraction.padEnd(2, "0");
  return `${sign}${currencySymbol}${currencySpacing}${groupedWhole},${cents}`;
}

export function toDecimalString(value: string): string {
  const cleaned = value.trim().replace(/^R\$\s*/i, "").replace(/\s/g, "");
  const commaIndex = cleaned.lastIndexOf(",");
  let whole = cleaned;
  let fraction = "";

  if (commaIndex >= 0) {
    whole = cleaned.slice(0, commaIndex).replace(/\./g, "");
    fraction = cleaned.slice(commaIndex + 1);
  } else {
    const dotCount = (cleaned.match(/\./g) ?? []).length;
    const dotIndex = cleaned.lastIndexOf(".");
    if (dotCount === 1 && cleaned.length - dotIndex - 1 <= 2) {
      whole = cleaned.slice(0, dotIndex);
      fraction = cleaned.slice(dotIndex + 1);
    } else {
      whole = cleaned.replace(/\./g, "");
    }
  }

  if (!/^[-+]?\d+$/.test(whole) || !/^\d{0,2}$/.test(fraction)) {
    throw new Error("Informe um valor com até duas casas decimais.");
  }

  const sign = whole.startsWith("-") ? "-" : "";
  const digits = whole.replace(/^[-+]/, "").replace(/^0+(?=\d)/, "");
  return `${sign}${digits}.${fraction.padEnd(2, "0")}`;
}

export function formatCurrencyInput(value: string): string {
  if (!value.trim()) return "";

  try {
    return formatCurrency(toDecimalString(value)).replace(/^R\$\s*/i, "");
  } catch {
    return value.trim().replace(/^R\$\s*/i, "");
  }
}

export function formatCurrencyInputForEditing(value: string): string {
  if (!value.trim()) return "";

  try {
    const decimal = toDecimalString(value);
    const match = /^(-?)(\d+)\.(\d{2})$/.exec(decimal);
    if (!match) return value.trim().replace(/^R\$\s*/i, "");
    const [, sign, whole, fraction] = match;
    return `${sign}${whole},${fraction}`;
  } catch {
    return value.trim().replace(/^R\$\s*/i, "");
  }
}
