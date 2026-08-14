"""Framework-neutral model usage contract for Product attribution."""

from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True, slots=True)
class AgentTokenUsage:
    """Normalized token buckets for one model request.

    Cached/audio buckets are subsets of input/output tokens and therefore are
    never added again when calculating ``total_tokens``.
    """

    input_tokens: int
    output_tokens: int
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    input_audio_tokens: int = 0
    cache_audio_read_tokens: int = 0
    output_audio_tokens: int = 0

    def __post_init__(self) -> None:
        counters = (
            self.input_tokens,
            self.output_tokens,
            self.cache_write_tokens,
            self.cache_read_tokens,
            self.input_audio_tokens,
            self.cache_audio_read_tokens,
            self.output_audio_tokens,
        )
        if any(value < 0 for value in counters):
            raise ValueError("token counters must be non-negative")

    @property
    def total_tokens(self) -> int:
        """Return inclusive input + output tokens without double-counting caches."""
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class AgentModelCallUsage:
    """Normalized evidence for one model request made during an Agent run.

    ``reported_model`` and ``provider_response_id`` are opaque gateway
    observations, not Product identities, an actual-provider guarantee, or a
    guaranteed LiteLLM call ID. ``token_usage=None`` means the provider did not
    report token usage; unknown must never be rewritten as zero.
    """

    call_index: int
    logical_model: str
    token_usage: AgentTokenUsage | None
    reported_model: str | None = None
    provider_response_id: str | None = None

    def __post_init__(self) -> None:
        if self.call_index < 0:
            raise ValueError("call_index must be non-negative")
        if not self.logical_model.strip():
            raise ValueError("logical_model must not be blank")


@dataclass(frozen=True, slots=True)
class AgentUsage:
    """Usage produced by one Agent execution, preserving every model call."""

    model_calls: tuple[AgentModelCallUsage, ...] = ()
    tool_calls: int = 0
    unattributed_model_requests: int = 0

    def __post_init__(self) -> None:
        if self.tool_calls < 0:
            raise ValueError("tool_calls must be non-negative")
        if self.unattributed_model_requests < 0:
            raise ValueError("unattributed_model_requests must be non-negative")
        call_indexes = tuple(call.call_index for call in self.model_calls)
        if call_indexes != tuple(range(len(self.model_calls))):
            raise ValueError("model call indexes must be contiguous and zero-based")

    @property
    def model_requests(self) -> int:
        return len(self.model_calls) + self.unattributed_model_requests

    @property
    def per_call_usage_complete(self) -> bool:
        return self.unattributed_model_requests == 0

    def _sum_token_counter(self, name: str) -> int | None:
        if not self.per_call_usage_complete:
            return None
        usages = tuple(call.token_usage for call in self.model_calls)
        if any(usage is None for usage in usages):
            return None
        return sum(
            cast(int, getattr(usage, name))
            for usage in usages
            if isinstance(usage, AgentTokenUsage)
        )

    @property
    def token_usage_available(self) -> bool:
        return self.per_call_usage_complete and all(
            call.token_usage is not None for call in self.model_calls
        )

    @property
    def input_tokens(self) -> int | None:
        return self._sum_token_counter("input_tokens")

    @property
    def output_tokens(self) -> int | None:
        return self._sum_token_counter("output_tokens")

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens

    @property
    def cache_write_tokens(self) -> int | None:
        return self._sum_token_counter("cache_write_tokens")

    @property
    def cache_read_tokens(self) -> int | None:
        return self._sum_token_counter("cache_read_tokens")
