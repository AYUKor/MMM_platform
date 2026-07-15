import type { DecisionResultV1 } from "../../entities/decision-result/types";

export type ResultProviderKind = "fixture" | "http" | "unavailable";

export interface ResultProvider {
  readonly kind: ResultProviderKind;
  getResult(resultId: string): Promise<DecisionResultV1>;
}

export class ResultProviderUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ResultProviderUnavailableError";
  }
}

export function createUnavailableResultProvider(message: string): ResultProvider {
  return {
    kind: "unavailable",
    async getResult() {
      throw new ResultProviderUnavailableError(message);
    },
  };
}
