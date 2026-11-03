// Hold the Nx project graph to its tags: a `type:contract` project (the specification
// and the conformance suite) depends on nothing, so no change to the crate or its e2e
// tier can reach it; `type:library` depends only on contracts; `type:e2e` only on the
// library it drives. Every project declares a recognized type tag. Node built-ins only;
// quiet on success.
import { lstatSync, readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const allowed = {
  "type:contract": [],
  "type:library": ["type:contract"],
  "type:e2e": ["type:library"],
  "type:workspace": [],
};
const skip = new Set(["node_modules", "target", ".git", ".nx"]);
const projects = new Map();
const walk = (dir) => {
  for (const entry of readdirSync(dir)) {
    if (skip.has(entry)) continue;
    const path = join(dir, entry);
    if (lstatSync(path).isDirectory()) walk(path);
    else if (entry === "project.json") {
      const project = JSON.parse(readFileSync(path, "utf8"));
      projects.set(project.name, { ...project, file: relative(root, path) });
    }
  }
};
walk(root);
const problems = [];
const typeOf = (project) => (project.tags ?? []).find((tag) => tag in allowed);
for (const project of projects.values()) {
  const type = typeOf(project);
  if (!type) {
    problems.push(`${project.file}: no type tag (one of ${Object.keys(allowed).join(", ")})`);
    continue;
  }
  for (const name of project.implicitDependencies ?? []) {
    const target = projects.get(name);
    const targetType = target && typeOf(target);
    if (!targetType || !allowed[type].includes(targetType)) {
      problems.push(`${project.file}: a ${type} project may not depend on ${name} (${targetType ?? "unknown"})`);
    }
  }
}
if (problems.length) {
  console.error(problems.join("\n"));
  console.error("check-project-boundaries: next: keep dependencies running library -> contract, e2e -> library");
  process.exit(1);
}
