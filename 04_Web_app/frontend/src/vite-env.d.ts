/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_RESULT_PROVIDER?: "fixture" | "http";
  readonly VITE_FIXTURE_VARIANT?: "safe" | "gate-blocked";
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
