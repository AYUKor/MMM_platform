export type FixtureVariant = "safe" | "gate-blocked";

const fixtureVariant: FixtureVariant =
  import.meta.env.VITE_FIXTURE_VARIANT === "gate-blocked"
    ? "gate-blocked"
    : "safe";

export const appEnv = {
  resultProvider: import.meta.env.VITE_RESULT_PROVIDER,
  fixtureVariant,
  isDevelopment: import.meta.env.DEV,
} as const;
