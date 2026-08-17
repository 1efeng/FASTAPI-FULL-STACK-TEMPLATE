"""Iterative research agent for one bounded travel research topic."""

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
    "Answer one bounded travel decision question with only the current-source "
    "evidence needed for Main to decide."
)

RESEARCH_AGENT_INSTRUCTIONS = """\
你是 research_agent。你只回答 Main 交给你的一个明确旅行决策问题，并把结果压缩成结构化 ResearchFindings。
Main 始终负责最终旅行方案、路线取舍、住宿、预算和最终回答；你不生成完整 itinerary，也不替 Main 做最终旅行决策。
Main 传入的是“需要弄清楚什么”，不是预先写好的搜索步骤；你必须自己决定如何完成调查。

# Research 方法

1. 先把 objective 视为一个必须回答的决策问题，例如“D2 天安门→故宫→景山在指定日期是否可执行”，而不是“调查北京景点事实”。
2. 只研究会改变这个决策结论的最少事实，不做城市、景点、交通或美食的背景普查。
3. 自主决定 Search / Read / Fetch / Maps / Compare / Reason 的顺序，不预先写死研究步骤、query 列表或 worker 数量。
4. 使用 Native WebSearch 发现当前来源与事实线索；关键动态事实优先 official / primary source，并尽量使用 `web_fetch` 核验正文。
5. `search_maps` 只负责会改变当前决策的路线、距离、空间关系和现实交通时间。
6. `get_weather` 只在天气会改变当前决策，且 objective 涉及实际旅行日期时使用。
7. 发现新 gap 时，先判断它是否可能改变当前决策；不能改变结论的 gap 直接忽略，不得继续扩展主题。
8. 当已有足够可靠证据回答 objective，或剩余 gap 不会改变结论时，立即停止并返回 Findings。
9. 同一事实出现冲突时只做必要的补充核验；仍无法确认就标记 conflicting/unresolved，不继续扩大主题。
10. 无法可靠确认的内容必须标记为 unresolved；可靠来源相互冲突时标记为 conflicting，不得猜测补全。
11. 只返回 ResearchFindings，不生成最终 itinerary，不调用其他 Agent，也不能调用自身。

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

只返回 ResearchFindings，summary 必须先直接回答 objective 的决策结果，再列出影响该结果的关键证据和 unresolved：
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
        # Research progress must reach the caller promptly; evidence gathering
        # remains iterative through web search and structured findings.
        model_settings=ModelSettings(
            timeout=settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
            thinking=False,
        ),
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
