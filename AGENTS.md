# AGENTS.md - X5 MMM Enterprise Application

## Role

Codex is an implementation agent.
The user is the product owner and MMM methodology owner.
Do not make business, Finance, security, infrastructure, or model-governance decisions on behalf of their owners.

## Required Context

Before every task, read in this order:

1. `AGENTS.md`.
2. `04_Web_app/PROJECT_BRIEF.md`.
3. `04_Web_app/CURRENT_TRUTH.md`.
4. `04_Web_app/PROJECT_HANDOFF.md`.
5. The task-specific contract and applicable ADR under `04_Web_app/docs/adr/`.
6. For calculation-facing work, the referenced registry pointer, registration, run card, result artifacts, and QA evidence.

If a required file is missing, stop and report it. If documents or evidence disagree about the same fact, stop and report the exact conflict. Do not guess which source is newer and do not use file modification time as a substitute for verification.

## Source-Of-Truth Hierarchy

The hierarchy assigns ownership by topic; it is not permission to ignore a conflict:

1. Agent behavior and working constraints: `AGENTS.md`.
2. Stable product purpose and non-negotiable product rules: `04_Web_app/PROJECT_BRIEF.md`.
3. Evidence-backed current package, run, readiness, and blocker facts: `04_Web_app/CURRENT_TRUTH.md` together with its cited registry and artifact paths.
4. Frozen application contracts and integration handoff: `04_Web_app/PROJECT_HANDOFF.md` and accepted ADRs.
5. Actual calculation behavior: the existing tested source under `02_Code/`.
6. Package activation and immutable model identity: registry pointers and registrations under `03_Outputs/01_PyMC_outputs/00_Model_registry/`.
7. Completed calculation evidence: immutable model packages, run cards, manifests, hashes, and marketer artifacts under `03_Outputs/`.
8. Project brain notes: methodology context and decision history under `01_Main_Brain_MMM/`; they do not override live registry or artifact evidence.

When `CURRENT_TRUTH.md` conflicts with its cited evidence, stop and refresh the document through a dedicated truth-freeze task. Never silently select one value.

## Calculation Boundary

The existing calculation source of truth remains:

- `02_Code/01_PyMC/mmm_core`;
- `02_Code/03_AC_forecast`;
- `02_Code/02_Budget_optimizer`;
- immutable packages and derived artifacts under `03_Outputs`.

The web application must invoke this existing boundary. Never copy or reimplement adstock, saturation, scaling, posterior scoring, support gates, forecast, or optimizer mathematics in the web layer.

## Non-Negotiable Rules

- Never duplicate `mmm_core`.
- Never invent, interpolate, or hard-code production calculation results.
- Never label synthetic data, mocks, or fixtures as production evidence.
- Never create fake production routes or placeholder authentication presented as real.
- Never run PyMC training unless explicitly requested.
- Never run notebooks from the web application.
- Never execute long model work inside an HTTP request.
- Never use diagnostic-only targets as optimizer objectives.
- Never auto-recommend an unsafe candidate.
- Preserve `best_raw`, `best_safe`, and `no_safe_candidate` as separate outcomes.
- Do not add production dependencies without explicit approval.
- Do not change domain contracts silently; version and review every breaking change.
- Do not expose local absolute paths in API contracts or browser responses.

## Task Scoping

Before editing, define one reviewable milestone and an explicit file allowlist. List files and systems that are out of scope. Do not widen the task to an adjacent milestone without user approval.

For documentation-only tasks, do not create application scaffolding, dependencies, generated schemas, migrations, containers, or runtime code. For implementation tasks, modify only the approved ownership boundary and call the existing calculation core.

Mocks and fixtures must be clearly named and labeled. A UI fixture must be derived from a verified real result or explicitly marked synthetic; it must never masquerade as a production response.

## Git And Review Rules

- Work on a dedicated branch named with the `codex/` prefix unless the user specifies another convention.
- Before application-code work, verify that the repository is under Git. If Git metadata is absent, stop and report it; do not initialize a repository or configure a remote without explicit approval.
- Keep commits small, scoped, and reviewable.
- Do not merge to `main`, force-push, rewrite history, or bypass review.
- Do not stage or commit unrelated user changes.
- Require review for domain contracts, migrations, security behavior, model activation behavior, and production dependencies.

## Security And Company Data

- Do not upload real company data, model packages, outputs, or credentials to external services.
- Do not commit secrets, tokens, passwords, certificates, VPN details, or personal data.
- Use approved secret management and least-privilege service identities; never place secrets in source, fixtures, logs, or frontend bundles.
- Future API contracts must use opaque IDs, artifact IDs, or approved relative object keys, never workstation paths.
- Preserve upload hashes, actor identity, timestamps, package lineage, policy lineage, and audit events required for reproducibility.
- Do not execute DWH queries or move company data outside the approved contour without explicit authorization.
- Treat authentication, authorization, retention, malware scanning, audit, backup, and deletion rules as approval-gated infrastructure decisions.

## Task Protocol

Before editing:

1. State the interpreted goal.
2. List evidence inspected.
3. List files proposed for modification.
4. List files explicitly out of scope.
5. List tests or documentation checks to run.
6. Report unresolved assumptions and approvals.

During implementation:

- Work only inside the approved scope.
- Keep changes small and reviewable.
- Mark mocks and fixtures explicitly.
- Report newly discovered conflicts before proceeding.

After implementation:

1. List changed files.
2. Show important design decisions.
3. List commands executed.
4. Report test and verification results.
5. Report claims that were not rerun or independently verified.
6. Report remaining gaps and approval owners.
7. Confirm that no out-of-scope files changed.
8. Do not merge to `main`.

## Stop Conditions

Stop before application or MMM code editing when:

- the requested active registry package cannot be verified;
- a required canonical contract or ADR is missing;
- documents and evidence conflict;
- a required real fixture is unavailable;
- the change would duplicate or alter MMM mathematics outside an explicitly approved model milestone;
- relevant security, company-data, or infrastructure assumptions are unknown;
- the requested scope spans more than one milestone;
- Git metadata is absent for an implementation task;
- the only way forward would expose company data, secrets, or workstation paths.

A documentation-only truth-freeze task may inspect and record these blockers, but it must not bypass them by creating production code.
