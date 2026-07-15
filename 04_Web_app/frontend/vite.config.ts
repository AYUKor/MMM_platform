/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

const configDir = dirname(fileURLToPath(import.meta.url));

function sanitizedFixturePlugin(): Plugin {
  const fixtures = {
    "/safe.json": "result_overview_v1_real_sanitized.json",
  } as const;

  return {
    name: "sanitized-result-overview-fixtures",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use(
        "/__fixtures/result-overview",
        async (request, response, next) => {
          const fixtureName = fixtures[request.url as keyof typeof fixtures];
          if (!fixtureName) {
            next();
            return;
          }
          try {
            const fixturePath = resolve(
              configDir,
              "../tests/fixtures",
              fixtureName,
            );
            const body = await readFile(fixturePath, "utf8");
            response.statusCode = 200;
            response.setHeader("Content-Type", "application/json; charset=utf-8");
            response.setHeader("Cache-Control", "no-store");
            response.end(body);
          } catch (error) {
            next(error as Error);
          }
        },
      );
    },
  };
}

export default defineConfig({
  plugins: [react(), sanitizedFixturePlugin()],
  server: {
    host: "127.0.0.1",
    port: 4173,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    css: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
    },
  },
});
