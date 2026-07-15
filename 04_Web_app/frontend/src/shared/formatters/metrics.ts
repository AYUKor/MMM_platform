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

export function formatSignedRub(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "Нет данных";
  const formatted = formatRub(Math.abs(value));
  if (value === 0) return formatted;
  return `${value > 0 ? "+" : "−"}${formatted}`;
}

export function formatDecimal(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "Нет данных";
  return decimalNumber.format(value);
}

export function formatInteger(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "Нет данных";
  return integerNumber.format(value);
}

export function formatPercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "Нет данных";
  return new Intl.NumberFormat("ru-RU", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatBytes(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value <= 0) return "Размер не указан";
  if (value < 1024) return `${integerNumber.format(value)} Б`;
  if (value < 1024 ** 2) return `${decimalNumber.format(value / 1024)} КБ`;
  return `${decimalNumber.format(value / 1024 ** 2)} МБ`;
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
