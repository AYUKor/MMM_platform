import type { ModelPassport } from "../../shared/api/generated/product-api-v1";

export type ModelPassportV1 = ModelPassport;

export type ModelPassportAllowedUse =
  ModelPassportV1["coverage"]["channel_policies"][number]["allowed_use"];

export type ModelPassportEvidenceStatus =
  ModelPassportV1["validation"]["historical_replay"]["status"];
