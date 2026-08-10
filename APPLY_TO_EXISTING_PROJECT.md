# 如何应用到你当前 Codex 项目

这是 **文档/上下文 overlay**，不是源码项目 ZIP。

它不会替换你已经存在的：

```text
backend/
frontend/
compose*.yml
pyproject.toml
uv.lock
```

建议：

```bash
git status
git checkout -b codex-handoff-v7
```

先提交或备份当前未提交工作。

把 ZIP 解压到当前项目根目录后先检查：

```bash
git status
git diff -- AGENTS.md CODEX_HANDOFF.md IMPLEMENTATION_NOTES.md docs/
```

确认无误再提交：

```bash
git add AGENTS.md CODEX_HANDOFF.md CODEX_START_PROMPT.md   IMPLEMENTATION_NOTES.md docs/

git commit -m "docs: establish v7 Codex handoff and build roadmap"
```

然后把 `CODEX_START_PROMPT.md` 内容发给 Codex。
