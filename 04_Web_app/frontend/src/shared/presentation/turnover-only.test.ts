import { describe, expect, it } from "vitest";
import { containsLegacyTargetClaim, keepTurnoverOnlyText } from "./turnover-only";

describe("turnover-only presentation guard", () => {
  it.each([
    "Дополнительные заказы показываются рядом с оборотом",
    "Количество заказов остается диагностическим показателем",
    "Средний чек помогает разложить результат",
    "orders_per_user",
    "avg_basket",
    "Модель оценивает три целевых показателя",
  ])("filters a legacy target claim: %s", (value) => {
    expect(containsLegacyTargetClaim(value)).toBe(true);
    expect(keepTurnoverOnlyText(value)).toBeNull();
  });

  it("keeps turnover, budget and uncertainty guidance", () => {
    const value = "Диапазон показывает неопределенность прогноза дополнительного оборота.";
    expect(containsLegacyTargetClaim(value)).toBe(false);
    expect(keepTurnoverOnlyText(value)).toBe(value);
  });
});
