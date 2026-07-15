import type { DecisionResultV1 } from "../../entities/decision-result/types";
import type { FixtureVariant } from "../config/env";
import type { ResultProvider } from "./result-provider";

export function createFixtureResultProvider(
  defaultVariant: FixtureVariant,
): ResultProvider {
  return {
    kind: "fixture",
    async getResult(resultId) {
      const variant = resultId.includes("gate-blocked")
        ? "gate-blocked"
        : defaultVariant;
      const response = await fetch(
        `/__fixtures/decision-result/${variant}.json`,
        { headers: { Accept: "application/json" } },
      );
      if (!response.ok) {
        throw new Error("Не удалось загрузить sanitized fixture.");
      }
      return (await response.json()) as unknown as DecisionResultV1;
    },
  };
}
