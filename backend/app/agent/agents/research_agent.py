"""Iterative research agent for one bounded travel research topic."""

from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel, Field, model_validator
from pydantic_ai import Agent
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


EvidenceToolName = Literal[
    "search_poi",
    "get_poi_detail",
    "search_nearby",
    "get_weather",
    "search_maps",
]


class EvidenceClaim(BaseModel):
    """One compressed claim and the evidence that supports it."""

    claim: str
    source_urls: list[str] = Field(default_factory=list)
    tool_evidence: list[EvidenceToolName] = Field(default_factory=list)
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


class VerificationItem(BaseModel):
    """One atomic fact that must be resolved for the Topic decision."""

    id: str = Field(min_length=1, max_length=80)
    entity: str = Field(min_length=1, max_length=120)
    aspect: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=320)


class VerificationResult(BaseModel):
    """Evidence-backed resolution of exactly one ``VerificationItem``."""

    item_id: str
    summary: str
    source_urls: list[str] = Field(default_factory=list)
    tool_evidence: list[EvidenceToolName] = Field(default_factory=list)
    status: Literal["verified", "conflicting", "unresolved"]

    @model_validator(mode="after")
    def resolved_result_requires_evidence(self) -> VerificationResult:
        if self.status in {"verified", "conflicting"} and not (
            self.source_urls or self.tool_evidence
        ):
            raise ValueError(
                "verified/conflicting verification results require evidence"
            )
        return self


class ResearchRequest(BaseModel):
    """Minimal handoff from Main into an isolated complex research task."""

    objective: str
    title: str | None = Field(default=None, max_length=80)
    verification_items: list[VerificationItem] = Field(default_factory=list)
    context: str | None = None
    constraints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def verification_item_ids_are_unique(self) -> ResearchRequest:
        item_ids = [item.id for item in self.verification_items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("verification item ids must be unique")
        return self


class ResearchFindings(BaseModel):
    """Compressed evidence-backed findings returned to Main."""

    topic: str
    summary: str | None = None
    verification_results: list[VerificationResult] = Field(default_factory=list)
    claims: list[EvidenceClaim] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)
    media: list[ImageAsset] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def verified_urls_must_exist_in_sources(self) -> ResearchFindings:
        declared_urls = {source.url for source in self.sources}
        result_ids = [result.item_id for result in self.verification_results]
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("verification result item ids must be unique")

        for claim in self.claims:
            if claim.status not in {"verified", "conflicting"}:
                continue
            missing = set(claim.source_urls) - declared_urls
            if missing:
                raise ValueError(
                    "verified/conflicting evidence references URL(s) missing from sources: "
                    + ", ".join(sorted(missing))
                )

        for result in self.verification_results:
            if result.status not in {"verified", "conflicting"}:
                continue
            missing = set(result.source_urls) - declared_urls
            if missing:
                raise ValueError(
                    "verified/conflicting evidence references URL(s) missing from sources: "
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
如果 request 包含 `verification_items`，它们是这个 Topic 的原子验收清单：每一次 Search / Fetch / Maps / Weather 都必须直接服务至少一个 item；不会改变任何 item 结论的调查必须停止。它们不是 query、tool sequence 或 reasoning steps。

# Research 方法

1. 先把 objective 视为一个必须回答的决策问题，例如“D2 天安门→故宫→景山在指定日期是否可执行”，而不是“调查北京景点事实”。
2. 只研究会改变这个决策结论的最少事实，不做城市、景点、交通或美食的背景普查。
3. 自主决定 Search / Read / Fetch / Maps / Compare / Reason 的顺序，不预先写死研究步骤、query 列表或 worker 数量。
4. 使用 `search_web` 发现当前来源与事实线索；关键动态事实优先 official / primary source，并尽量使用 `web_fetch` 核验正文。需要非常权威来源时可设置 `authoritative=true`；首次召回不佳或 query 过于口语化时才启用 `query_rewrite`。
5. POI 名称、坐标、地址、评分、人均、电话、营业时间、入口与附近地点优先使用 `search_poi` / `get_poi_detail` / `search_nearby`，不要为了这些结构化地点事实先做 Web 搜索。
6. POI 调研先最小化调用：通常 `search_poi` 找中心点，再一次 `search_nearby` 即可完成附近候选筛选。`search_nearby` 已返回 distance/rating/cost 时，不得为了重复确认这些字段逐个调用 `get_poi_detail`；只有当前决策确实缺少营业时间、入口、电话等 detail-only 字段时才补一个或少量详情。
7. 不得在未观察到本轮 POI 搜索结果前猜测 POI ID 并调用 `get_poi_detail`。附近半径/距离已经足以回答“约 X 公里范围内”时，不要再调用 `search_maps`；只有真实路线耗时/交通方式会改变决策时才查路线。
8. `search_maps` 只负责会改变当前决策的路线、距离、空间关系和现实交通时间。
9. `get_weather` 只在天气会改变当前决策，且 objective 涉及实际旅行日期时使用。
10. 发现新 gap 时，先判断它是否可能改变当前决策；不能改变结论的 gap 直接忽略，不得继续扩展主题。
11. 如果 request 有 `verification_items`，优先逐项解决这些 item；不得为了“顺便完善行程”调查 checklist 之外的局部路线、景点或价格。
12. 当已有足够可靠证据回答 objective，或剩余 gap 不会改变结论时，立即停止并返回 Findings。
13. 同一事实出现冲突时只做必要的补充核验；仍无法确认就标记 conflicting/unresolved，不继续扩大主题。
14. 无法可靠确认的内容必须标记为 unresolved；可靠来源相互冲突时标记为 conflicting，不得猜测补全。
15. 只返回 ResearchFindings，不生成最终 itinerary，不调用其他 Agent，也不能调用自身。

# 证据边界

- `verified` Web 事实必须引用本轮真实成功执行的 `search_web` / `web_fetch` trajectory 中实际出现的 URL，并把这些 URL 同时列入 `source_urls` / `sources`；不得虚构 URL，也不得仅凭“搜索过”自证。
- POI / 天气 / 地图事实只能使用实际成功执行过的 `search_poi` / `get_poi_detail` / `search_nearby` / `get_weather` / `search_maps` 作为 tool evidence。
- POI tool evidence 只证明高德返回的地点、商业、位置与营业信息；预约、放票、临时闭馆、政策等动态规则仍必须用 Web/官方来源核验。
- 不能通过自己填写 URL 或 Tool 名称来“自证”；Host 会再次核验真实执行轨迹，只保留实际执行过的 evidence。
- 当前动态事实不得使用模型训练记忆补写。
- 搜索 snippet 主要用于 discovery；关键动态事实尽量打开官方 / primary source 正文核验。
- `media` 仅作为现有兼容字段保留；本轮不要围绕图片扩张研究架构，图片来源也不能单独作为动态事实证据。

# 金额

事实价格使用当地货币并明确币种，不自行做最终预算或汇率换算。

# 输出

只返回 ResearchFindings，summary 必须先直接回答 objective 的决策结果，再列出影响该结果的关键证据和 unresolved。

如果 request 包含 `verification_items`：
- 每个 input item 必须返回且只返回一条 `verification_results`；
- `item_id` 必须原样匹配 input id；
- 没有足够证据时返回 unresolved，不得省略；
- 不得新增 checklist 外的 result。

输出字段：
- topic
- summary
- verification_results
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

    return cast(
        Agent[object, ResearchFindings],
        Agent(
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
            tools=build_research_tools(include_web_search=True),
            capabilities=(ResearchAgentRuntimeCapability(),),
            output_type=ResearchFindings,
            defer_model_check=True,
        ),
    )
