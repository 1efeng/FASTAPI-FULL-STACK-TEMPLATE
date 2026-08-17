import { apiFetch } from "@/lib/auth"
import type { ProductUIMessage } from "./use-product-chat"

export type DurableMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  reasoning_summary: string | null
  source_urls?: string[]
  created_at: string
}

export type ConversationDetail = {
  id: string
  title: string | null
  last_message_at: string | null
  created_at: string
  updated_at: string
  messages: DurableMessage[]
}

export class ConversationLoadError extends Error {
  constructor(readonly status: number) {
    super(`failed to load conversation: ${status}`)
  }
}

export async function loadConversation(
  conversationId: string,
): Promise<ConversationDetail> {
  const response = await apiFetch(`/api/v1/conversations/${conversationId}`, {})
  if (!response.ok) {
    throw new ConversationLoadError(response.status)
  }
  return (await response.json()) as ConversationDetail
}

export function toUIMessages(messages: DurableMessage[]): ProductUIMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role,
    parts: [
      ...(message.role === "assistant" && message.reasoning_summary
        ? ([
            {
              type: "reasoning",
              text: message.reasoning_summary,
              state: "done",
            },
          ] as const)
        : []),
      { type: "text", text: message.content, state: "done" } as const,
      ...(message.role === "assistant"
        ? (message.source_urls ?? []).map((url) => ({
            type: "source-url" as const,
            sourceId: url,
            url,
            title: url,
          }))
        : []),
    ],
  }))
}
