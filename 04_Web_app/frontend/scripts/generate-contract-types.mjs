import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const contracts = [
  {
    schema: "decision_result_v1.schema.json",
    typeName: "DecisionResultV1",
    output: "decision-result-v1.ts",
  },
  {
    schema: "application_lifecycle_v1.schema.json",
    typeName: "ApplicationLifecycleV1",
    output: "application-lifecycle-v1.ts",
  },
];

for (const contract of contracts) {
  const schemaPath = resolve(scriptDir, "../../contracts", contract.schema);
  const outputPath = resolve(
    scriptDir,
    "../src/shared/api/generated",
    contract.output,
  );
  const schema = JSON.parse(await readFile(schemaPath, "utf8"));
  const source = await compile(schema, contract.typeName, {
    bannerComment: `/* Generated from ../../contracts/${contract.schema}. Do not edit manually. */`,
    style: { singleQuote: false, semi: true, tabWidth: 2 },
  });
  await writeFile(outputPath, source, "utf8");
}
