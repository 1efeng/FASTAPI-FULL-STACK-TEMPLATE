import { Check, Copy } from "lucide-react"

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

type ResearchProgress = {
  topic: string
  status: "started" | "checking" | "completed" | "unresolved"
  label: string
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
        typeof value.status === "string"
      )
    })
  const isReasoningStreaming =
    isLastAssistant &&
    isStreaming &&
    reasoningParts.some((part) => part.state === "streaming")
  const showStreamingPlaceholder =
    !isUser && isLastAssistant && isStreaming && !text && !hasReasoning

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

            {researchProgress.length > 0 && (
              <div className="mb-3 space-y-1 rounded-lg border border-border/60 bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
                {researchProgress.map((progress, index) => (
                  <div className="flex gap-2" key={`${progress.topic}-${index}`}>
                    <span aria-hidden="true">
                      {progress.status === "completed"
                        ? "✓"
                        : progress.status === "unresolved"
                          ? "!"
                          : "·"}
                    </span>
                    <span>{progress.label}</span>
                  </div>
                ))}
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
