import { describe, expect, it } from "vitest";
import {
  formatDecimal,
  formatMetricValue,
  formatRub,
} from "./metrics";

describe("metric formatters", () => {
  it("formats values with Russian locale", () => {
    expect(formatDecimal(3.09155)).toBe("3,09");
    expect(formatRub(84_627_166.71)).toContain("₽");
  });

  it("renders missing values as controlled no-data state", () => {
    expect(formatDecimal(null)).toBe("Нет данных");
    expect(formatMetricValue(null, "RUB")).toBe("Нет данных");
  });
});
