# 完整替换说明

本包是完整文档体系，不是局部 patch。

推荐替换方式：

```bash
cd <travel-agent-project>
rm -rf docs
rm -f AGENTS.md README.md IMPLEMENTATION_NOTES.md
unzip -o travel_agent_v6_documentation_full_refactor_framework_ownership.zip -d .
```

如果仓库 README 还包含大量业务运行说明，请先备份并把仍然有效的“运行命令”合并回新 README；不要把旧架构说明重新带回。

替换后检查：

```bash
find docs -type f -maxdepth 2 | sort
rg "P0-1 Central LLM Gateway|P0-4 LLM Usage Ledger|P0-6 Conversation Persistence \+ Context Budget" .
```

第二条理想情况下不应命中旧 P0 标题。
