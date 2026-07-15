import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const schemaPath = resolve(scriptDir, "../../contracts/decision_result_v1.schema.json");
const outputPath = resolve(
  scriptDir,
  "../src/shared/api/generated/decision-result-v1.ts",
);

const schema = JSON.parse(await readFile(schemaPath, "utf8"));
const source = await compile(schema, "DecisionResultV1", {
  bannerComment:
    "/* Generated from ../../contracts/decision_result_v1.schema.json. Do not edit manually. */",
  style: { singleQuote: false, semi: true, tabWidth: 2 },
});

await writeFile(outputPath, source, "utf8");
