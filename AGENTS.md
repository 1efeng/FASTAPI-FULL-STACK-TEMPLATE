# AGENTS.md — Travel Agent Cursor Execution Rules

> This file contains only long-lived execution rules.
> Do not store current milestone, commit hash, temporary debug state, or short-lived implementation status here.

## 1. Role

Cursor is the implementation executor.

When the current task already defines architecture, scope, stages, gates, or acceptance criteria:
- implement them faithfully;
- do not redesign them on your own;
- do not expand scope for unrelated cleanup.

If current code makes the approved plan impossible or unsafe, stop and report the conflict before changing architecture.

## 2. Source of Truth

The project completed a documentation/architecture reset on 2026-08-19. Do not use pre-reset architecture documents as current design input.

Use these sources by role, not as one mixed priority list:

1. The currently approved task and acceptance criteria.
2. `docs/产品文档.md` for current Product WHAT / WHY.
3. `docs/架构.md` for TARGET architecture **only after that document explicitly says Architecture Baseline is accepted**.
4. Current workspace code and tests for CURRENT implementation reality.
5. Active post-reset contracts / READMEs only after they are explicitly re-created or re-adopted under the new Architecture Baseline.
6. Locked dependency versions and official APIs for implementation facts.

The Active Docs allowlist is defined in `docs/文档体系.md`. Every pre-reset `docs/**` file outside that allowlist is Historical / NON-SOT even if it still exists at its old path for CURRENT implementation reference.

`docs/archive/**`, pre-reset contracts, and pre-reset ADRs are historical evidence only. They are never a Source of Truth unless a current approved task explicitly re-adopts a decision.

`docs/施工路线图.md` is not authoritative until it is rebuilt after Product + Architecture baselines are accepted.

Never infer current project state from old chats, old commits, old branches, archived docs, or stale text in this file.

When CURRENT code and TARGET docs differ:
- code/tests describe CURRENT behavior;
- accepted Product / Architecture docs describe TARGET behavior;
- report the mismatch instead of silently redesigning or making docs look artificially consistent.

## 3. Minimal Scope

Make the smallest change required by the current stage.

Do not, unless explicitly approved:
- perform unrelated refactors;
- upgrade dependencies or alter version pins;
- patch or vendor third-party libraries;
- change public contracts;
- change persistence ownership;
- change timeout / retry / fallback policy;
- weaken auth, authorization, tenant isolation, tests, typing, or runtime safety limits;
- overwrite unrelated uncommitted user changes.

Check `git status --short` before editing.

## 4. Staged Work

When work is divided into stages such as A0 / A1 / B1:
- execute only the explicitly approved stage;
- run that stage's acceptance tests;
- report the result;
- stop and wait for approval;
- never continue automatically to the next stage.

Valid stage results:

- `PASS`
- `FAIL`
- `ENVIRONMENT_BLOCKED`
- `BLOCKED`

`ENVIRONMENT_BLOCKED` means the verification environment failed, not necessarily the product code.

## 5. Test Environment

Before modifying product code because a test cannot access:
- Docker;
- Redis;
- PostgreSQL;
- LiteLLM;
- localhost / private network;
- Playwright browser;
- external model or travel providers;

first determine whether the failure is environmental.

If the shell, network, service, credentials, socket, or local runtime prevents verification:
- report `ENVIRONMENT_BLOCKED`;
- include the failing command and exact error;
- do not modify product code to work around Cursor's execution environment.

Run the smallest relevant tests first, then expand only as required by the active gate.

## 6. Safety

Never run destructive operations without explicit approval, including:
- `git reset --hard`;
- `git clean`;
- force push;
- destructive database reset / DROP / TRUNCATE;
- `docker volume rm`;
- `docker system prune`;
- `docker compose down -v`;
- recursive destructive file deletion.

Never expose secrets, API keys, tokens, private keys, real `.env` values, or production credentials.

## 7. Architecture Guardrail

The 2026-08-19 reset intentionally removed legacy architecture ownership from this long-lived execution file.

Until `docs/架构.md` is explicitly accepted as the new Architecture Baseline:
- do not treat the current framework, Agent topology, runtime ownership, persistence choice, gateway choice, Search/Research design, or context strategy as permanent TARGET architecture merely because it exists in code;
- also do not rewrite CURRENT code speculatively during the design reset;
- preserve CURRENT behavior unless an approved implementation task explicitly changes it.

After the new Architecture Baseline is accepted:
- implement it faithfully;
- core architecture changes require an approved architecture task / ADR;
- Prompt changes, Tool routing, token/context limits, provider tuning, and benchmark-driven performance work are implementation changes unless they actually violate a frozen architecture invariant.

Never use archived architecture documents to reconstruct old guardrails.

## 8. Reporting

After an approved implementation stage, report:

- `STAGE`
- `RESULT`
- files changed
- what changed and why
- commands run
- test results
- environment limitations
- git diff summary
- risks / open questions

Then stop and wait for approval.
