import { describe, expect, it } from "vitest";
import {
  formatDecimal,
  formatBytes,
  formatMetricValue,
  formatPercent,
  formatRub,
  formatSignedRub,
} from "./metrics";

describe("metric formatters", () => {
  it("formats values with Russian locale", () => {
    expect(formatDecimal(3.09155)).toBe("3,09");
    expect(formatRub(84_627_166.71)).toContain("₽");
    expect(formatPercent(0.953)).toBe("95,3 %");
    expect(formatSignedRub(-1_000)).toContain("−");
    expect(formatBytes(1024)).toBe("1 КБ");
  });

  it("renders missing values as controlled no-data state", () => {
    expect(formatDecimal(null)).toBe("Нет данных");
    expect(formatMetricValue(null, "RUB")).toBe("Нет данных");
  });
});
