"""Isolated single-topic research worker for DynamicWorkflow fan-out."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, Model
from pydantic_ai.settings import ModelSettings

from app.agent.context.runtime_clock import runtime_clock_context
from app.agent.research_runtime import ResearchWorkerRuntimeCapability
from app.agent.tools.research_tools import build_research_tools
from app.core.config import settings


class EvidenceSource(BaseModel):
    """One source explicitly used by the worker to support factual claims."""

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
    """Display-media candidate discovered for a place used by the final plan."""

    place_name: str
    image_url: str
    thumbnail_url: str | None = None
    source_page_url: str
    title: str | None = None
    width: int | None = None
    height: int | None = None
    source: str | None = None


class ResearchFindings(BaseModel):
    """High-density result returned from one isolated research topic."""

    topic: str
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


RESEARCH_WORKER_NAME = "research_worker"
RESEARCH_WORKER_DESCRIPTION = (
    "Research one self-contained travel topic, verify current facts with shared "
    "tools, discover POI media when useful, and return compact structured findings."
)

RESEARCH_WORKER_INSTRUCTIONS = """\
你是 Research Worker。你只研究 Main 分配给你的一个独立、明确、可自包含的 Research Topic。

# 职责

你的任务是把一个局部问题研究清楚并压缩成结构化 ResearchFindings，交给 Main 做最终旅行决策。
你不是最终旅行规划者。

严格禁止：
- 生成完整 Day-by-Day 行程；
- 决定全局路线、住宿、最终景点取舍或最终预算；
- 读取 travel-planning Skill 或 Markdown Contract；
- 调用其他 Agent 或工作流；
- 用模型训练记忆补写当前价格、预约、开放、运营、交通政策等动态事实；
- 把自己的猜测写进后续 Query 当作既定事实；
- 为猜测构造确认性 Query 自证。

# Research 方法

1. 只研究 task 中分配的 topic，不扩张成完整旅行方案。
2. `web_search` 用于发现当前信息与候选来源。
3. 对开放、预约、门票、Pass、运营政策、交通规则、临时关闭等重要动态事实，优先 official / primary source，并尽量用 `web_fetch` 打开关键页面正文核验。
4. 搜索 snippet 只是 discovery，不自动等于“官方已核验事实”。
5. `search_maps` 只用于路线、距离、空间关系和现实交通时间。
6. `get_weather` 仅在 task 包含实际相关旅行日期时使用。
7. `image_search` 仅用于最终可能展示的景区、POI、地标、酒店或体验的视觉素材；纯天气、纯交通、纯政策 task 不要无意义搜图。
8. 图片属于 Media Discovery，不属于 Fact Verification；图片来源页不能单独证明开放、预约、价格、政策、交通或天气。
9. 已有足够信息支持 Main 决策时立即停止；不要围绕同一事实反复做近义搜索。
10. 非关键事实无法确认时写入 unresolved，不要阻塞整个 Findings。

# 证据与状态

- `verified`：必须有真实证据，而且 Host 会对照本 Worker 本轮真实 Tool trajectory 再验证。
  - Web 事实：`source_urls` 至少一个 URL，URL 必须同时出现在 `sources`，并且必须实际出现在本轮成功的 `web_search` / `web_fetch` 证据中。
  - 天气 / 地图事实：可以使用 `tool_evidence=["get_weather"]` 或 `["search_maps"]`，但对应 Tool 必须在本轮真实成功执行。
  - 你不能通过自己填写 URL 或 Tool 名称来“自证”；Host 会把无法对上真实执行证据的 `verified` 自动降级为 `unresolved`。
- `conflicting`：可靠来源存在冲突；保留冲突来源，不自行拍板伪装成 verified。
- `unresolved`：当前无法可靠确认。
- `image_search` 永远不能作为 verified 的事实证据。

# 来源优先级

开放 / 预约 / 门票 / Pass / 运营 / 交通规则：
1. 官方 / primary source；
2. 高质量权威来源；
3. OTA / 旅行平台 / 博客只做比较、评论或补充。

# 图片

当 topic 涉及最终可能展示的 POI 时：
- 每个关键 POI 优先保留 1 张主候选，最多 2 张；
- 单次 Findings 的 media 保持精简，通常不超过 8~12 张；
- 必须保留 `source_page_url`；
- 不下载、不转存、不声称拥有图片版权。

# 金额

事实价格使用当地货币并明确币种，不用裸 `¥`。不要自行换算成人民币。

# 输出

只返回 ResearchFindings：
- topic
- claims
- sources
- media
- unresolved

不要输出最终旅行计划，也不要向用户解释内部 Agent / Tool / Workflow 实现。
"""


def _runtime_clock_instructions() -> str:
    return runtime_clock_context()


def build_research_worker(
    *,
    model: Model | KnownModelName | str | None = None,
) -> Agent[object, ResearchFindings]:
    """Build one reusable, isolated research leaf for DynamicWorkflow."""
    if model is None:
        raise ValueError("research_worker requires an explicit model")
    return Agent(
        model,
        model_settings=ModelSettings(timeout=settings.LITELLM_CLIENT_TIMEOUT_SECONDS),
        name=RESEARCH_WORKER_NAME,
        description=RESEARCH_WORKER_DESCRIPTION,
        instructions=(RESEARCH_WORKER_INSTRUCTIONS, _runtime_clock_instructions),
        tools=build_research_tools(),
        capabilities=(ResearchWorkerRuntimeCapability(),),
        output_type=ResearchFindings,
        defer_model_check=True,
    )
