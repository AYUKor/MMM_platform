const compactNumber = new Intl.NumberFormat("ru-RU", {
  notation: "compact",
  maximumFractionDigits: 1,
});

const decimalNumber = new Intl.NumberFormat("ru-RU", {
  maximumFractionDigits: 2,
});

const integerNumber = new Intl.NumberFormat("ru-RU", {
  maximumFractionDigits: 0,
});

const dateFormatter = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

export function formatRub(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "Нет данных";
  return `${compactNumber.format(value)} ₽`;
}

export function formatDecimal(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "Нет данных";
  return decimalNumber.format(value);
}

export function formatInteger(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "Нет данных";
  return integerNumber.format(value);
}

export function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.valueOf()) ? value : dateFormatter.format(date);
}

export function formatMetricValue(
  value: number | null,
  unit: string | null,
): string {
  if (unit === "RUB") return formatRub(value);
  return formatDecimal(value);
}
