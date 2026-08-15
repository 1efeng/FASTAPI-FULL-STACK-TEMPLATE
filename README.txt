Travel Agent v8 — lightweight Cursor configuration

Install:
1. Replace the repository-root AGENTS.md with this AGENTS.md.
2. Copy .cursor/rules/staged-execution.mdc into the repository.
3. Keep Legacy Terminal Tool enabled if that is the terminal mode that works in your environment.
4. Do NOT restore .cursor/sandbox.json; it caused Agent chat to hang in this workspace.
5. For the current Cursor installation, remove/disable .cursor/permissions.json unless Run Mode is actually exposed and enabled. Cursor documents that permissions.json only takes effect when Run Mode is enabled.

Recommended final layout:

AGENTS.md
.cursor/
  rules/
    staged-execution.mdc

No sandbox.json.
No permissions.json for now.

Why this is lighter:
- AGENTS.md only contains durable, always-relevant constraints.
- Current milestone/progress stays in docs/施工路线图.md.
- Detailed staged Gate behavior is loaded conditionally by Cursor based on the rule description rather than being injected into every chat.
