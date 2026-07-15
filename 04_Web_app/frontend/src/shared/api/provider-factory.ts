import { appEnv } from "../config/env";
import { createFixtureResultProvider } from "./fixture-result-provider";
import { createHttpResultProvider } from "./http-result-provider";
import {
  createUnavailableResultProvider,
  type ResultProvider,
} from "./result-provider";

export function createResultProvider(): ResultProvider {
  if (appEnv.resultProvider === "http") {
    return createHttpResultProvider(appEnv.apiBaseUrl);
  }

  if (appEnv.resultProvider === "fixture" && appEnv.isDevelopment) {
    return createFixtureResultProvider(appEnv.fixtureVariant);
  }

  if (appEnv.resultProvider === "fixture") {
    return createUnavailableResultProvider(
      "Fixture provider запрещён вне development-сборки.",
    );
  }

  return createUnavailableResultProvider(
    "API provider ещё не реализован. Результат недоступен.",
  );
}
