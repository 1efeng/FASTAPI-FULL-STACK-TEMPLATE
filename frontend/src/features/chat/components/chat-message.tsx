import { Check, Copy } from "lucide-react"
import { useEffect, useState } from "react"

import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message"
import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning"
import { Shimmer } from "@/components/ai-elements/shimmer"
import type { ProductUIMessage } from "@/features/chat/use-product-chat"
import { cn } from "@/lib/utils"

type ChatMessageProps = {
  message: ProductUIMessage
  isLastAssistant: boolean
  isStreaming: boolean
  copiedMessageId: string | null
  onCopy: (messageId: string, text: string) => void
}

type VerificationItemStatus =
  | "pending"
  | "verified"
  | "conflicting"
  | "unresolved"

type VerificationItemProgress = {
  id: string
  entity: string
  aspect: string
  question: string
  status: VerificationItemStatus
  summary?: string
}

type ResearchProgress = {
  topic: string
  status: "started" | "checking" | "completed" | "unresolved"
  stage:
    | "research"
    | "analysis"
    | "web_search"
    | "web_fetch"
    | "maps"
    | "weather"
    | "tool"
    | "verification"
  label: string
  topic_title?: string
  verification_items?: VerificationItemProgress[]
  item_id?: string
  entity?: string
  aspect?: string
  item_status?: Exclude<VerificationItemStatus, "pending">
  item_summary?: string
}

type ResearchTopicProgress = {
  topic: string
  title: string
  events: ResearchProgress[]
  items: VerificationItemProgress[]
}

function isVerificationItemProgress(
  value: unknown,
): value is VerificationItemProgress {
  if (!value || typeof value !== "object") return false
  const item = value as Partial<VerificationItemProgress>
  return (
    typeof item.id === "string" &&
    typeof item.entity === "string" &&
    typeof item.aspect === "string" &&
    typeof item.question === "string" &&
    item.status === "pending"
  )
}

function isVerificationItemStatus(
  value: unknown,
): value is Exclude<VerificationItemStatus, "pending"> {
  return (
    value === "verified" || value === "conflicting" || value === "unresolved"
  )
}

/**
 * Avatar-free message layout: user bubble on the right, assistant text on the left.
 */
export function ChatMessage({
  message,
  isLastAssistant,
  isStreaming,
  copiedMessageId,
  onCopy,
}: ChatMessageProps) {
  const isUser = message.role === "user"
  const text = message.parts
    .filter((part) => part.type === "text")
    .map((part) => (part.type === "text" ? part.text : ""))
    .join("")
  const reasoningParts = message.parts.filter(
    (part) => part.type === "reasoning",
  )
  const hasReasoning = reasoningParts.length > 0
  const reasoning = reasoningParts.map((part) => part.text).join("")
  const researchProgress = message.parts
    .filter((part) => part.type === "data-research-progress")
    .map((part) => ("data" in part ? part.data : null))
    .filter((data): data is ResearchProgress => {
      if (!data || typeof data !== "object") return false
      const value = data as Partial<ResearchProgress>
      return (
        typeof value.topic === "string" &&
        typeof value.label === "string" &&
        typeof value.status === "string" &&
        typeof value.stage === "string"
      )
    })
  const researchTopics = researchProgress.reduce<ResearchTopicProgress[]>(
    (topics, progress) => {
      let topic = topics.find((item) => item.topic === progress.topic)
      if (!topic) {
        topic = {
          topic: progress.topic,
          title: progress.topic_title || progress.topic,
          events: [],
          items: [],
        }
        topics.push(topic)
      }

      if (progress.topic_title) topic.title = progress.topic_title

      const snapshotItems = Array.isArray(progress.verification_items)
        ? progress.verification_items.filter(isVerificationItemProgress)
        : []
      for (const snapshot of snapshotItems) {
        const existingItem = topic.items.find((item) => item.id === snapshot.id)
        if (existingItem) {
          existingItem.entity = snapshot.entity
          existingItem.aspect = snapshot.aspect
          existingItem.question = snapshot.question
        } else {
          topic.items.push({ ...snapshot })
        }
      }

      if (
        progress.item_id &&
        progress.entity &&
        progress.aspect &&
        isVerificationItemStatus(progress.item_status)
      ) {
        const existingItem = topic.items.find(
          (item) => item.id === progress.item_id,
        )
        if (existingItem) {
          existingItem.status = progress.item_status
          existingItem.summary = progress.item_summary
        } else {
          topic.items.push({
            id: progress.item_id,
            entity: progress.entity,
            aspect: progress.aspect,
            question: progress.aspect,
            status: progress.item_status,
            summary: progress.item_summary,
          })
        }
      }

      const previous = topic.events.at(-1)
      if (
        !previous ||
        previous.label !== progress.label ||
        previous.status !== progress.status ||
        previous.stage !== progress.stage ||
        previous.item_id !== progress.item_id
      ) {
        topic.events.push(progress)
      }
      return topics
    },
    [],
  )
  const isReasoningStreaming =
    isLastAssistant &&
    isStreaming &&
    reasoningParts.some((part) => part.state === "streaming")
  const isResearchRunning =
    !isUser &&
    isLastAssistant &&
    isStreaming &&
    researchTopics.some(
      ({ events }) =>
        !events.some(
          (event) =>
            event.stage === "research" &&
            (event.status === "completed" || event.status === "unresolved"),
        ),
    )
  const [researchElapsedSeconds, setResearchElapsedSeconds] = useState(0)

  useEffect(() => {
    if (!isResearchRunning) return
    const startedAt = Date.now()
    setResearchElapsedSeconds(0)
    const timer = window.setInterval(() => {
      setResearchElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [isResearchRunning])

  const showStreamingPlaceholder =
    !isUser &&
    isLastAssistant &&
    isStreaming &&
    !text &&
    !hasReasoning &&
    researchTopics.length === 0

  return (
    <Message
      className={cn("w-full max-w-full", isUser && "ml-0")}
      from={message.role}
    >
      <div
        className={cn(
          "flex w-full items-start",
          isUser ? "justify-end" : "justify-start",
        )}
      >
        <div
          className={cn("min-w-0", isUser ? "max-w-[78%] flex-none" : "w-full")}
        >
          <MessageContent
            className={cn(
              "text-base leading-7",
              isUser
                ? "w-auto rounded-[18px] bg-[#f1f2f4] px-4 py-2.5 text-foreground group-[.is-user]:ml-0 group-[.is-user]:rounded-[18px] group-[.is-user]:bg-[#f1f2f4] group-[.is-user]:px-4 group-[.is-user]:py-2.5 dark:bg-white/10 dark:group-[.is-user]:bg-white/10"
                : "w-full bg-transparent px-0 py-0 text-foreground",
            )}
          >
            {hasReasoning && (
              <Reasoning
                className="w-full"
                isReasoningStreaming={isReasoningStreaming}
                isStreaming={isStreaming}
              >
                <ReasoningTrigger
                  className="gap-2.5 text-base [&_svg]:size-5"
                  getThinkingMessage={(streaming) =>
                    streaming ? (
                      <Shimmer duration={1}>正在思考...</Shimmer>
                    ) : (
                      <span>已思考</span>
                    )
                  }
                />
                {reasoning && (
                  <ReasoningContent className="mt-3 border-l-2 border-primary/15 pl-4 leading-7">
                    {reasoning}
                  </ReasoningContent>
                )}
              </Reasoning>
            )}

            {researchTopics.length > 0 && (
              <div
                aria-live="polite"
                className="mb-3 space-y-4 rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5 text-sm text-muted-foreground"
              >
                <div className="flex items-center justify-between gap-3 border-b border-border/50 pb-2">
                  <div className="flex items-center gap-2 font-medium text-foreground/90">
                    {isResearchRunning ? (
                      <Shimmer duration={1.2}>正在研究并核验最新信息</Shimmer>
                    ) : (
                      <>
                        <Check aria-hidden="true" className="size-4" />
                        <span>研究核验已结束</span>
                      </>
                    )}
                  </div>
                  <span className="shrink-0 text-xs tabular-nums">
                    {researchTopics.length} 个主题
                    {isResearchRunning ? ` · ${researchElapsedSeconds}s` : ""}
                  </span>
                </div>

                {researchTopics.map(({ topic, title, events, items }) => {
                  const terminal = [...events]
                    .reverse()
                    .find(
                      (event) =>
                        event.stage === "research" &&
                        (event.status === "completed" ||
                          event.status === "unresolved"),
                    )
                  const isTopicRunning = !terminal
                  const verifiedCount = items.filter(
                    (item) => item.status === "verified",
                  ).length
                  const unresolvedCount = items.filter(
                    (item) =>
                      item.status === "unresolved" ||
                      item.status === "conflicting",
                  ).length
                  const groupedItems = items.reduce<
                    Record<string, VerificationItemProgress[]>
                  >((groups, item) => {
                    groups[item.entity] ??= []
                    groups[item.entity].push(item)
                    return groups
                  }, {})
                  const executionEvents = events.filter(
                    (event) =>
                      event.stage !== "research" &&
                      event.stage !== "verification",
                  )
                  const activeEvent = [...executionEvents]
                    .reverse()
                    .find(
                      (event) =>
                        event.status === "checking" &&
                        (event.label.startsWith("正在") ||
                          event.label.startsWith("已发起")),
                    )
                  const activeLabel = activeEvent
                    ? activeEvent.label.startsWith("已发起")
                      ? activeEvent.label.replace("已发起", "正在")
                      : activeEvent.label
                    : "正在继续核验剩余项目"
                  const detailEvents = executionEvents.filter(
                    (event) =>
                      !event.label.startsWith("正在") &&
                      !event.label.startsWith("已发起"),
                  )
                  const topicMarker = isTopicRunning
                    ? "·"
                    : terminal.status === "unresolved" || unresolvedCount > 0
                      ? "!"
                      : "✓"

                  return (
                    <div className="space-y-2" key={topic}>
                      <div className="flex items-start gap-2">
                        <span
                          aria-hidden="true"
                          className="mt-0.5 flex w-3 shrink-0 justify-center font-medium text-foreground/80"
                        >
                          {topicMarker}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="font-medium leading-5 text-foreground/90">
                            {title}
                          </div>
                          {items.length > 0 && (
                            <div className="mt-0.5 text-xs text-muted-foreground">
                              {verifiedCount}/{items.length} 已确认
                              {unresolvedCount > 0
                                ? ` · ${unresolvedCount} 项待确认`
                                : ""}
                            </div>
                          )}
                        </div>
                      </div>

                      {items.length > 0 && (
                        <div className="ml-5 space-y-2">
                          {Object.entries(groupedItems).map(
                            ([entity, entityItems]) => (
                              <div className="space-y-0.5" key={entity}>
                                <div className="text-xs font-medium text-foreground/75">
                                  {entity}
                                </div>
                                {entityItems.map((item) => (
                                  <div
                                    className="flex items-start gap-2 text-sm"
                                    key={item.id}
                                    title={item.summary}
                                  >
                                    <span
                                      aria-hidden="true"
                                      className="w-3 shrink-0 text-center"
                                    >
                                      {item.status === "verified"
                                        ? "✓"
                                        : item.status === "conflicting" ||
                                            item.status === "unresolved"
                                          ? "!"
                                          : "·"}
                                    </span>
                                    <span>
                                      {item.aspect}
                                      {item.status === "conflicting"
                                        ? " · 来源冲突"
                                        : item.status === "unresolved"
                                          ? " · 暂未确认"
                                          : ""}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            ),
                          )}
                        </div>
                      )}

                      {isTopicRunning && (
                        <div className="ml-5 text-sm">
                          <Shimmer duration={1.2}>{activeLabel}</Shimmer>
                        </div>
                      )}

                      {detailEvents.length > 0 && (
                        <details className="ml-5 text-xs text-muted-foreground/90">
                          <summary className="cursor-pointer select-none py-0.5 hover:text-foreground/80">
                            查看研究详情
                          </summary>
                          <div className="mt-1 space-y-0.5 border-l border-border/60 pl-3">
                            {detailEvents.map((event, index) => (
                              <div
                                className="flex items-start gap-2"
                                key={`${event.stage}-${event.label}-${index}`}
                              >
                                <span
                                  aria-hidden="true"
                                  className="w-3 shrink-0"
                                >
                                  {event.status === "unresolved" ? "!" : "✓"}
                                </span>
                                <span>{event.label}</span>
                              </div>
                            ))}
                          </div>
                        </details>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {text && (
              <MessageResponse
                className={cn(
                  "[&_li]:my-1 [&_ol]:my-3 [&_p]:leading-7 [&_ul]:my-3",
                  isUser ? "[&_p]:my-0" : "[&_p]:my-3",
                )}
              >
                {text}
              </MessageResponse>
            )}

            {showStreamingPlaceholder && (
              <div className="py-1 text-sm text-muted-foreground">
                <Shimmer duration={1}>正在思考...</Shimmer>
              </div>
            )}
          </MessageContent>

          {!isUser && text && !(isLastAssistant && isStreaming) && (
            <MessageActions>
              <MessageAction
                aria-label="复制消息"
                className="size-7 text-muted-foreground opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
                label="复制"
                onClick={() => onCopy(message.id, text)}
                size="icon-sm"
                tooltip={copiedMessageId === message.id ? "已复制" : "复制"}
                variant="ghost"
              >
                {copiedMessageId === message.id ? (
                  <Check className="size-3.5" />
                ) : (
                  <Copy className="size-3.5" />
                )}
              </MessageAction>
            </MessageActions>
          )}
        </div>
      </div>
    </Message>
  )
}
