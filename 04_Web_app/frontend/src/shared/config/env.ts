export type FixtureVariant = "safe" | "gate-blocked";

const fixtureVariant: FixtureVariant =
  import.meta.env.VITE_FIXTURE_VARIANT === "gate-blocked"
    ? "gate-blocked"
    : "safe";

export const appEnv = {
  resultProvider: import.meta.env.VITE_RESULT_PROVIDER,
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8765",
  fixtureVariant,
  isDevelopment: import.meta.env.DEV,
} as const;
