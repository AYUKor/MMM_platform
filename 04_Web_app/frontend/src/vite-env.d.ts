/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_RESULT_PROVIDER?: "fixture";
  readonly VITE_FIXTURE_VARIANT?: "safe" | "gate-blocked";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
