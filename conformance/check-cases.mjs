// The case files' own shape, checked before any implementation runs them: every file
// parses, every case has a unique id, a known operation, the inputs that operation needs,
// a non-empty `exercises` list and an `expect` with an `outcome`. What the cases *mean* is
// checked by running them (crates/privateterms/tests/conformance.rs). Node built-ins
// only; quiet on success.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const dir = new URL("./cases/", import.meta.url).pathname;
const needs = {
  validate: [],
  resolve: [],
  detect: ["text"],
  replace: ["text"],
  "screen-locators": ["locators"],
};
const ids = new Set();
const problems = [];
for (const file of readdirSync(dir).filter((f) => f.endsWith(".json")).sort()) {
  let document;
  try {
    document = JSON.parse(readFileSync(join(dir, file), "utf8"));
  } catch (error) {
    problems.push(`${file}: not JSON (${error.message})`);
    continue;
  }
  for (const [index, c] of (document.cases ?? []).entries()) {
    const where = `${file}#${c.id ?? `case ${index + 1}`}`;
    if (typeof c.id !== "string") problems.push(`${where}: no id`);
    else if (ids.has(c.id)) problems.push(`${where}: duplicate id`);
    else ids.add(c.id);
    if (!(c.operation in needs)) problems.push(`${where}: unknown operation ${c.operation}`);
    for (const member of needs[c.operation] ?? []) {
      if (!(member in c)) problems.push(`${where}: ${c.operation} needs \`${member}\``);
    }
    if (!Array.isArray(c.exercises) || c.exercises.length === 0) problems.push(`${where}: cites no rule`);
    if (typeof c.expect?.outcome !== "string") problems.push(`${where}: no expected outcome`);
  }
}
if (ids.size === 0) problems.push("no cases at all");
if (problems.length) {
  console.error(problems.join("\n"));
  console.error("check-cases: next: fix the case files as conformance/README.md lays them out");
  process.exit(1);
}
