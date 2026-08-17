# ADR-0010: Skill-Owned Travel Planning + Topic-Level Multi Research Delegation

## Status

Accepted — amends ADR-0009 for Travel Planning ownership and Research Agent multiplicity / parallelism.

## Context

ADR-0009 established Candidate Plan First and an iterative `research_agent`, but v1 still kept two limitations:

1. detailed Travel Planning SOP and Research routing were duplicated between Main instructions and the `travel-planning` Skill;
2. a Host gate allowed at most one `research_agent` call per Main run, so multiple independent research topics could not execute concurrently.

Real travel plans often expose several independent research themes after a Candidate Plan is formed. A Beijing three-day plan may need one coherent topic for attraction reservation/opening constraints and another independent topic for intercity + Badaling transport. Treating every fact as Main-owned search bloats Main context; forcing all topics into one child loses topic boundaries; limiting the whole run to one child prevents natural parallelism.

The architecture also needs to remain extensible for future non-travel Skills. Domain SOP must not accumulate in the global Main prompt.

## Decision

### 1. Main remains domain-neutral

`MAIN_AGENT_INSTRUCTIONS` contains only cross-domain behavior:

- user-intent handling and minimal clarification;
- Runtime clock ownership;
- generic Skill / Tool / specialist-agent boundaries;
- current-fact trust rules;
- deterministic-computation boundaries;
- user-visible reasoning/privacy rules;
- Main ownership of final integration and final answer.

Travel-specific planning policy does not live in Main instructions.

### 2. `travel-planning` Skill is the Travel Planning SOT

The Skill owns:

- travel slots and clarification policy;
- Candidate Plan First;
- Reality Gap identification;
- Research Topic formation and routing;
- route / schedule quality;
- Weather / Maps usage semantics;
- Budget / FX semantics;
- revision behavior;
- final itinerary contract.

### 3. Main splits Research Topics; Research Agent splits Research Steps

After Candidate Plan creation, Main identifies Reality Gaps.

An isolated fact remains Main-owned and can use Native Search / `web_fetch` / Maps / Weather directly.

Related Reality Gaps that form one coherent investigation are grouped into one bounded Research Topic and delegated through:

```text
research_agent(
  objective,
  context,
  constraints,
)
```

Main specifies what must be understood, not how to search it. The child chooses its own Search / Read / Fetch / Maps / Compare / Reason / gap-finding sequence.

### 4. One Main run may delegate 0..N Research Topics

There is no fixed Research Agent call-count gate.

One coherent Research Topic normally maps to one `research_agent` call. Main must neither split a topic into many micro-agents nor force unrelated topics into one objective only to reduce call count.

Existing Main and child request/tool usage limits remain the resource bounds.

### 5. Independent topics may execute concurrently

When Main emits multiple independent `research_agent` tool calls in one model turn, PydanticAI's normal non-sequential function-tool execution provides concurrency.

No DynamicWorkflow, explicit worker fan-out, Python `asyncio.gather` orchestration layer, Planner, Supervisor, or Agent Team is introduced.

Topics with information dependencies execute in stages:

```text
Research A
→ Main evaluates Findings A
→ Research B only if A changes the remaining problem
```

### 6. Child isolation remains strict

Each child run has:

- fresh child model context;
- research-only tool surface;
- independent evidence trace;
- independent request/tool usage limits;
- structured `ResearchFindings` output.

The child cannot call itself or other Agents and does not own final itinerary, global route, accommodation choice, final budget, or final user response.

### 7. Parallel failure semantics

A recoverable child provider/output failure (`ModelAPIError` / `UnexpectedModelBehavior`) is converted at the `research_agent` capability boundary into unresolved `ResearchFindings` for that topic, so one independent topic does not abort sibling topics or the whole Main plan.

Parent cancellation and hard child `UsageLimitExceeded` are not swallowed and continue to propagate according to Runtime ownership.

### 8. Product Runtime ownership is unchanged

Conversation, Message, RequestRun, Streaming, PostgreSQL, Redis, cancellation ownership, billing/quota accounting, and Product durability remain unchanged.

Product usage continues to aggregate Main + every child Research run.

## Consequences

### Positive

- Main instructions stay small and extensible as more domain Skills are added;
- Travel planning behavior has one domain Source of Truth;
- Main context avoids long search trajectories for topic-level investigation;
- multiple independent research themes can reduce wall-clock time through framework-native parallel tool execution;
- topic dependencies remain explicit and staged;
- usage, evidence and cancellation boundaries remain observable and testable;
- no return to the removed DynamicWorkflow / research_worker architecture.

### Trade-offs

- real-model quality still depends on Main correctly grouping Reality Gaps into useful topics;
- overly broad topics can make child research unfocused, while overly narrow topics can create micro-agent churn;
- provider-native search citation metadata may remain incomplete; evidence behavior is constrained by actual tool/provider capabilities;
- parallel child execution increases instantaneous model/tool concurrency and must remain within Product/provider capacity limits.

## Supersedes / Amends

This ADR keeps ADR-0009's Candidate Plan First, iterative child research, structured Findings, evidence attestation and Product Runtime ownership.

It supersedes ADR-0009's v1 trade-offs that limited a Main run to one complex Research Agent call and deferred independent-topic parallelism.
