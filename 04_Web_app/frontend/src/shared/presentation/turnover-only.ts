const LEGACY_TARGET_CLAIM_RE = new RegExp(
  [
    "заказ[\\p{L}-]*",
    "средн[\\p{L}-]*\\s+чек",
    "orders?_per_user",
    "avg_basket",
    "тр(?:и|[её]х|[её]м)\\s+(?:целев[\\p{L}-]*\\s+)?показател",
    "3\\s+(?:целев[\\p{L}-]*\\s+)?показател",
    "тр(?:и|[её]х|[её]м)\\s+таргет",
    "three[-\\s]target",
  ].join("|"),
  "iu",
);

/**
 * Detects legacy multi-target product claims that must not be presented by the
 * turnover-only application. Campaign names and other arbitrary business text
 * are deliberately not passed through this helper.
 */
export function containsLegacyTargetClaim(value: string): boolean {
  return LEGACY_TARGET_CLAIM_RE.test(value);
}

export function keepTurnoverOnlyText(value: string): string | null {
  return containsLegacyTargetClaim(value) ? null : value;
}
