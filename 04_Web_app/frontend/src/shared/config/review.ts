export const SYNTHETIC_REVIEW_STORAGE_KEY = "mmm-review-data";

export function isSyntheticReview(): boolean {
  return import.meta.env.DEV && typeof window !== "undefined" &&
    window.localStorage.getItem(SYNTHETIC_REVIEW_STORAGE_KEY) === "synthetic";
}
