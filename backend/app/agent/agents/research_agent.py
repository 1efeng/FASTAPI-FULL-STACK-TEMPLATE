"""Iterative research agent for one complex travel research objective."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_ai import Agent, WebSearchTool
from pydantic_ai.capabilities import WebSearch
from pydantic_ai.models import KnownModelName, Model
from pydantic_ai.settings import ModelSettings

from app.agent.context.runtime_clock import runtime_clock_context
from app.agent.research_runtime import ResearchAgentRuntimeCapability
from app.agent.tools.research_tools import build_research_tools
from app.core.config import settings


class EvidenceSource(BaseModel):
    """One source explicitly used to support factual research claims."""

    title: str
    url: str
    source_type: str | None = None


class EvidenceClaim(BaseModel):
    """One compressed claim and the evidence that supports it."""

    claim: str
    source_urls: list[str] = Field(default_factory=list)
    tool_evidence: list[Literal["get_weather", "search_maps"]] = Field(
        default_factory=list
    )
    status: Literal["verified", "conflicting", "unresolved"]

    @model_validator(mode="after")
    def verified_claim_requires_evidence(self) -> EvidenceClaim:
        if self.status == "verified" and not (
            self.source_urls or self.tool_evidence
        ):
            raise ValueError(
                "verified claims require source_urls or dedicated tool evidence"
            )
        return self


class ImageAsset(BaseModel):
    """Display-media candidate retained only for compatibility/presentation."""

    place_name: str
    image_url: str
    thumbnail_url: str | None = None
    source_page_url: str
    title: str | None = None
    width: int | None = None
    height: int | None = None
    source: str | None = None


class ResearchRequest(BaseModel):
    """Minimal handoff from Main into an isolated complex research task."""

    objective: str
    context: str | None = None
    constraints: list[str] = Field(default_factory=list)


class ResearchFindings(BaseModel):
    """Compressed evidence-backed findings returned to Main."""

    topic: str
    summary: str | None = None
    claims: list[EvidenceClaim] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)
    media: list[ImageAsset] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def verified_urls_must_exist_in_sources(self) -> ResearchFindings:
        declared_urls = {source.url for source in self.sources}
        for claim in self.claims:
            if claim.status != "verified":
                continue
            missing = set(claim.source_urls) - declared_urls
            if missing:
                raise ValueError(
                    "verified claim references URL(s) missing from sources: "
                    + ", ".join(sorted(missing))
                )
        return self


RESEARCH_AGENT_NAME = "research_agent"
RESEARCH_AGENT_DESCRIPTION = (
    "Investigate one complex travel research objective with iterative current-source "
    "verification and return compact structured findings for Main to decide from."
)

RESEARCH_AGENT_INSTRUCTIONS = """\
你是 research_agent。你只研究 Main 交给你的一个明确复杂研究 objective，并把结果压缩成结构化 ResearchFindings。
Main 始终负责最终旅行方案、路线取舍、住宿、预算和最终回答；你不生成完整 itinerary，也不替 Main 做最终旅行决策。

# Research 方法

1. 只研究 Main 给出的 objective，并只使用完成该研究所需的 context 与 constraints。
2. 根据当前证据决定下一步要查什么，不预先写死研究轴或并行数量。
3. 使用 Native WebSearch 发现当前来源与事实线索。
4. 对价格、开放、预约、Pass、运营政策、交通规则、临时关闭等关键动态事实，优先 official / primary source，并尽量使用 `web_fetch` 打开关键页面核验。
5. `search_maps` 只负责路线、距离、空间关系和现实交通时间。
6. `get_weather` 只在 objective 涉及实际旅行日期天气时使用。
7. 如果现有证据暴露新的、会影响 Main 决策的信息缺口，继续 Search → Read → Reason → Find gaps → Search again。
8. 信息已经足够支持 Main 做决策时停止，不围绕同一事实反复近义搜索。
9. 无法可靠确认的内容必须标记为 unresolved；可靠来源相互冲突时标记为 conflicting，不得猜测补全。
10. 只返回 ResearchFindings，不生成最终 itinerary，不调用其他 Agent，也不能调用自身。

# 证据边界

- `verified` Web 事实必须引用本轮真实 Native WebSearch / `web_fetch` trajectory 中出现的 URL，并把 URL 同时列入 `sources`。
- 天气 / 地图事实只能使用实际成功执行过的 `get_weather` / `search_maps` 作为 tool evidence。
- 不能通过自己填写 URL 或 Tool 名称来“自证”；Host 会再次核验真实执行轨迹。
- 当前动态事实不得使用模型训练记忆补写。
- 搜索 snippet 主要用于 discovery；关键动态事实尽量打开官方 / primary source 正文核验。
- `media` 仅作为现有兼容字段保留；本轮不要围绕图片扩张研究架构，图片来源也不能单独作为动态事实证据。

# 金额

事实价格使用当地货币并明确币种，不自行做最终预算或汇率换算。

# 输出

只返回 ResearchFindings：
- topic
- summary
- claims
- sources
- media
- unresolved
"""


def _runtime_clock_instructions() -> str:
    return runtime_clock_context()


def build_research_agent(
    *,
    model: Model | KnownModelName | str | None = None,
) -> Agent[object, ResearchFindings]:
    """Build the reusable iterative research agent used by Main delegation."""

    if model is None:
        raise ValueError("research_agent requires an explicit model")

    return Agent(
        model,
        model_settings=ModelSettings(timeout=settings.LITELLM_CLIENT_TIMEOUT_SECONDS),
        name=RESEARCH_AGENT_NAME,
        description=RESEARCH_AGENT_DESCRIPTION,
        instructions=(RESEARCH_AGENT_INSTRUCTIONS, _runtime_clock_instructions),
        tools=build_research_tools(),
        capabilities=(
            WebSearch(native=WebSearchTool(optional=True)),
            ResearchAgentRuntimeCapability(),
        ),
        output_type=ResearchFindings,
        defer_model_check=True,
    )
