import type { ResultOverviewV1 } from "../../entities/result-overview/types";

export type ResultProviderKind = "fixture" | "http" | "unavailable";

export interface ResultProvider {
  readonly kind: ResultProviderKind;
  getOverview(jobId: string): Promise<ResultOverviewV1>;
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
    async getOverview() {
      throw new ResultProviderUnavailableError(message);
    },
  };
}
