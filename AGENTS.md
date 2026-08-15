# AGENTS.md — Travel Agent v8 Cursor Execution Rules

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

Use this order:

1. The currently approved task and acceptance criteria.
2. Current workspace code and tests.
3. `docs/架构v8.md` for TARGET architecture and ownership.
4. `docs/施工路线图.md` for CURRENT → TARGET progress and gate status.
5. Relevant contracts / READMEs.
6. Locked dependency versions and official APIs.

Never infer current project state from old chats, old commits, old branches, or stale text in this file.

When code and docs differ:
- code is CURRENT;
- architecture docs describe TARGET unless explicitly marked current;
- report the mismatch instead of making docs look artificially consistent.

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

Do not change established runtime ownership unless the current task explicitly approves it.

For Agent/runtime work, preserve these principles:
- Product lifecycle belongs to the FastAPI Product Runtime.
- Product → Agent execution crosses the `AgentExecutor` boundary.
- Pydantic AI owns the agent loop.
- Harness owns Skills/SubAgents capability composition.
- LiteLLM owns provider routing, provider retry, and fallback.
- PostgreSQL is the business source of truth.
- Redis is coordination infrastructure.
- Stream resume is not execution durability.
- Network disconnect is not Product Cancel.
- Product Stop must use the Product cancellation lifecycle.

For exact current architecture, read `docs/架构v8.md`; do not duplicate it here.

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
