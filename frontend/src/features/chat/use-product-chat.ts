import { useChat } from "@ai-sdk/react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { DefaultChatTransport, type UIMessage } from "ai"
import { useCallback, useEffect, useMemo, useRef } from "react"

const CONVERSATION_KEY = "travel_agent_conversation_id"
const REQUEST_KEY = "travel_agent_request_id"
const ACTIVE_REQUEST_KEY = "travel_agent_active_request"
const TOKEN_KEY = "access_token"

type DurableMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  reasoning_summary: string | null
  reasoning_duration_ms: number | null
  created_at: string
}

export type ProductUIMessage = UIMessage<{
  reasoningDurationMs?: number
}>

type ConversationDetail = {
  id: string
  title: string | null
  last_message_at: string | null
  created_at: string
  updated_at: string
  messages: DurableMessage[]
}

type RequestRun = {
  request_id: string
  conversation_id: string
  status: "running" | "completed" | "failed" | "cancelled"
}

type ActiveRequest = {
  requestId: string
  conversationId: string
}

class ConversationLoadError extends Error {
  constructor(readonly status: number) {
    super(`failed to load conversation: ${status}`)
  }
}

type UseProductChatOptions = {
  conversationId?: string
  onConversationChange?: (conversationId: string) => void
  onConversationUnavailable?: () => void
}

function bearerToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ""
}

async function loadConversation(
  conversationId: string,
): Promise<ConversationDetail> {
  const response = await fetch(`/api/v1/conversations/${conversationId}`, {
    headers: { Authorization: `Bearer ${bearerToken()}` },
  })
  if (!response.ok) {
    throw new ConversationLoadError(response.status)
  }
  return (await response.json()) as ConversationDetail
}

function toUIMessages(messages: DurableMessage[]): ProductUIMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role,
    ...(typeof message.reasoning_duration_ms === "number"
      ? { metadata: { reasoningDurationMs: message.reasoning_duration_ms } }
      : {}),
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
    ],
  }))
}

function mergeDurableReasoningMetadata(
  messages: ProductUIMessage[],
  durableMessages: DurableMessage[],
): ProductUIMessage[] {
  const durableAssistants = durableMessages.filter(
    (message) => message.role === "assistant",
  )
  let assistantIndex = 0

  return messages.map((message) => {
    if (message.role !== "assistant") return message

    const durableMessage = durableAssistants[assistantIndex]
    assistantIndex += 1
    if (typeof durableMessage?.reasoning_duration_ms !== "number") {
      return message
    }

    return {
      ...message,
      metadata: {
        ...message.metadata,
        reasoningDurationMs: durableMessage.reasoning_duration_ms,
      },
    }
  })
}

function saveActiveRequest(requestId: string, conversationId: string): void {
  const activeRequest: ActiveRequest = { requestId, conversationId }
  localStorage.setItem(ACTIVE_REQUEST_KEY, JSON.stringify(activeRequest))
  // Keep the old key during the M8 spike so an already-open tab can still be
  // refreshed after deploying this version.
  localStorage.setItem(REQUEST_KEY, requestId)
}

function readActiveRequest(conversationId: string): ActiveRequest | null {
  const encoded = localStorage.getItem(ACTIVE_REQUEST_KEY)
  if (encoded) {
    try {
      const activeRequest = JSON.parse(encoded) as Partial<ActiveRequest>
      if (
        activeRequest.conversationId === conversationId &&
        typeof activeRequest.requestId === "string"
      ) {
        return {
          requestId: activeRequest.requestId,
          conversationId,
        }
      }
      return null
    } catch {
      localStorage.removeItem(ACTIVE_REQUEST_KEY)
    }
  }

  const legacyRequestId = localStorage.getItem(REQUEST_KEY)
  return legacyRequestId ? { requestId: legacyRequestId, conversationId } : null
}

function clearActiveRequest(activeRequest: ActiveRequest): void {
  const current = readActiveRequest(activeRequest.conversationId)
  if (current?.requestId !== activeRequest.requestId) return
  localStorage.removeItem(ACTIVE_REQUEST_KEY)
  if (localStorage.getItem(REQUEST_KEY) === activeRequest.requestId) {
    localStorage.removeItem(REQUEST_KEY)
  }
}

async function loadRequestRun(requestId: string): Promise<RequestRun | null> {
  const response = await fetch(`/api/v1/chat/requests/${requestId}`, {
    headers: { Authorization: `Bearer ${bearerToken()}` },
  })
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(`failed to load request status: ${response.status}`)
  }
  return (await response.json()) as RequestRun
}

/**
 * Ensure an owned Product conversation exists, lazily creating one and
 * persisting its id. Returns the conversation id as a string.
 */
async function ensureConversationId(
  preferredId?: string,
  title?: string,
): Promise<string> {
  const existing = preferredId ?? localStorage.getItem(CONVERSATION_KEY)
  if (existing) {
    // Conversation ids survive a page refresh, but the database may have been
    // reset or the conversation may have been deleted.  Reusing such an id
    // makes the streaming endpoint open a 200 SSE response and fail only later
    // in its background producer, which AI SDK reports as ``network error``.
    const check = await fetch(`/api/v1/conversations/${existing}`, {
      headers: { Authorization: `Bearer ${bearerToken()}` },
    })
    if (check.ok) return existing
    if (check.status !== 404) {
      throw new Error(`failed to validate conversation: ${check.status}`)
    }
    localStorage.removeItem(CONVERSATION_KEY)
  }

  const response = await fetch("/api/v1/conversations/", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${bearerToken()}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title: title ?? "新的旅行咨询" }),
  })
  if (!response.ok) {
    throw new Error(`failed to create conversation: ${response.status}`)
  }
  const data = (await response.json()) as { id: string }
  localStorage.setItem(CONVERSATION_KEY, data.id)
  return data.id
}

function conversationTitle(messages: ProductUIMessage[]): string {
  const lastUserMessage = [...messages]
    .reverse()
    .find((message) => message.role === "user")
  const text = lastUserMessage?.parts
    .filter((part) => part.type === "text")
    .map((part) => (part.type === "text" ? part.text : ""))
    .join("")
    .trim()
  if (!text) return "新的旅行咨询"
  return text.length > 40 ? `${text.slice(0, 40)}…` : text
}

/**
 * Observe Product chat transport responses. The backend alone decides whether
 * a reconnectable stream exists; the browser only records a 204 so it can
 * refresh Product durable state after AI SDK returns to ready.
 */
function productChatFetch(
  getConversationId: () => string | undefined,
  onRequestId?: (requestId: string) => void,
  onReconnectUnavailable?: () => void,
): typeof globalThis.fetch {
  return async (input, init) => {
    const response = await fetch(input, init)
    if (init?.method === "GET" && response.status === 204) {
      onReconnectUnavailable?.()
    }
    const requestId = response.headers.get("X-Request-Id")
    const currentConversationId = getConversationId()
    if (requestId && currentConversationId) {
      onRequestId?.(requestId)
      saveActiveRequest(requestId, currentConversationId)
    }
    return response
  }
}

/**
 * Product chat hook: AI SDK active-stream state wired to the Product streaming
 * endpoint. Each send carries an Idempotency-Key and the owned conversation id;
 * reconnect (F5) re-attaches to the active stream via the Product stream endpoint.
 */
export function useProductChat({
  conversationId,
  onConversationChange,
  onConversationUnavailable,
}: UseProductChatOptions = {}) {
  const queryClient = useQueryClient()
  const requestIdRef = useRef<string | null>(null)
  const conversationIdRef = useRef(conversationId)
  const hydratedConversationRef = useRef<string | null>(null)
  const resumeAttemptedRef = useRef<string | null>(null)
  const unavailableReconnectRef = useRef<string | null>(null)
  const reconcileConversationRef = useRef<string | null>(null)

  conversationIdRef.current = conversationId

  const conversationQuery = useQuery<ConversationDetail, ConversationLoadError>(
    {
      queryKey: ["conversation", conversationId],
      queryFn: () => loadConversation(conversationId as string),
      enabled: Boolean(conversationId),
      retry: false,
    },
  )

  const transport = useMemo(
    () =>
      new DefaultChatTransport<ProductUIMessage>({
        api: "/api/v1/chat/stream",
        fetch: productChatFetch(
          () => conversationIdRef.current,
          (requestId) => {
            requestIdRef.current = requestId
          },
          () => {
            unavailableReconnectRef.current = requestIdRef.current
          },
        ),
        headers: () => ({
          Authorization: `Bearer ${bearerToken()}`,
        }),
        prepareSendMessagesRequest: async ({ body, headers, messages, id }) => {
          const resolvedConversationId = await ensureConversationId(
            conversationIdRef.current,
            conversationTitle(messages),
          )
          if (resolvedConversationId !== conversationIdRef.current) {
            conversationIdRef.current = resolvedConversationId
            // This hook already owns the live UI state for a newly-created
            // conversation. Do not overwrite it with an early durable snapshot
            // when the URL update causes the detail query to start.
            hydratedConversationRef.current = resolvedConversationId
            onConversationChange?.(resolvedConversationId)
            void queryClient.invalidateQueries({
              queryKey: ["conversations"],
            })
          }
          const idempotencyKey =
            typeof crypto !== "undefined" && crypto.randomUUID
              ? crypto.randomUUID()
              : Math.random().toString(36).slice(2)

          return {
            body: {
              ...body,
              id,
              messages,
              conversation_id: resolvedConversationId,
            },
            headers: {
              ...(headers as Record<string, string> | undefined),
              "Idempotency-Key": idempotencyKey,
            },
          }
        },
        prepareReconnectToStreamRequest: async ({ headers }) => {
          const currentConversationId = conversationIdRef.current
          const activeRequest = currentConversationId
            ? readActiveRequest(currentConversationId)
            : null
          const requestId =
            requestIdRef.current ?? activeRequest?.requestId ?? null
          return {
            api: requestId
              ? `/api/v1/chat/requests/${requestId}/stream`
              : "/api/v1/chat/stream",
            headers: {
              ...(headers as Record<string, string> | undefined),
              Authorization: `Bearer ${bearerToken()}`,
            },
          }
        },
      }),
    [onConversationChange, queryClient],
  )

  const chat = useChat<ProductUIMessage>({
    transport,
    onFinish: ({ isAbort, isDisconnect, isError }) => {
      const currentConversationId = conversationIdRef.current
      // Browser refresh/navigation aborts only the subscriber. Preserve the
      // active request hint so the next page instance can reconnect.
      if (!currentConversationId || isAbort || isDisconnect) return
      const activeRequest = readActiveRequest(currentConversationId)
      if (activeRequest) clearActiveRequest(activeRequest)
      if (!isError) {
        reconcileConversationRef.current = currentConversationId
      }
      void queryClient.invalidateQueries({
        queryKey: ["conversation", currentConversationId],
      })
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
    },
  })
  const stopChat = chat.stop
  const cancelRequest = useCallback(async () => {
    const currentConversationId = conversationIdRef.current
    const activeRequest = currentConversationId
      ? readActiveRequest(currentConversationId)
      : null
    const requestId = requestIdRef.current ?? activeRequest?.requestId ?? null
    if (!requestId) return

    const response = await fetch(`/api/v1/chat/requests/${requestId}/cancel`, {
      method: "POST",
      headers: { Authorization: `Bearer ${bearerToken()}` },
    })
    if (!response.ok) {
      throw new Error(`failed to cancel request: ${response.status}`)
    }

    // Product cancellation is authoritative.  Only detach the AI SDK
    // subscriber after the Product endpoint has accepted the terminal state.
    stopChat()
    requestIdRef.current = null
    if (activeRequest) clearActiveRequest(activeRequest)
    if (currentConversationId) {
      await queryClient.invalidateQueries({
        queryKey: ["conversation", currentConversationId],
      })
    }
  }, [queryClient, stopChat])
  const { resumeStream, setMessages, status } = chat

  useEffect(() => {
    if (conversationId || status !== "ready") return
    if (hydratedConversationRef.current !== null) {
      hydratedConversationRef.current = null
      resumeAttemptedRef.current = null
      requestIdRef.current = null
      setMessages([])
    }
  }, [conversationId, setMessages, status])

  useEffect(() => {
    if (
      !conversationId ||
      reconcileConversationRef.current !== conversationId ||
      !conversationQuery.data ||
      conversationQuery.isFetching ||
      status !== "ready"
    ) {
      return
    }

    const durableAssistantCount = conversationQuery.data.messages.filter(
      (message) => message.role === "assistant",
    ).length
    const uiAssistantCount = chat.messages.filter(
      (message) => message.role === "assistant",
    ).length
    if (durableAssistantCount < uiAssistantCount) return

    setMessages((messages) =>
      mergeDurableReasoningMetadata(messages, conversationQuery.data.messages),
    )
    reconcileConversationRef.current = null
  }, [
    chat.messages,
    conversationId,
    conversationQuery.data,
    conversationQuery.isFetching,
    setMessages,
    status,
  ])

  useEffect(() => {
    if (!conversationId || !conversationQuery.data) return

    localStorage.setItem(CONVERSATION_KEY, conversationId)
    if (
      hydratedConversationRef.current !== conversationId &&
      status === "ready"
    ) {
      setMessages(toUIMessages(conversationQuery.data.messages))
      hydratedConversationRef.current = conversationId
    }

    const activeRequest = readActiveRequest(conversationId)
    if (!activeRequest) return

    const attemptKey = `${conversationId}:${activeRequest.requestId}`
    if (
      resumeAttemptedRef.current === attemptKey ||
      hydratedConversationRef.current !== conversationId ||
      status !== "ready"
    ) {
      return
    }
    resumeAttemptedRef.current = attemptKey
    requestIdRef.current = activeRequest.requestId
    unavailableReconnectRef.current = null

    void (async () => {
      try {
        await resumeStream()
        if (unavailableReconnectRef.current === activeRequest.requestId) {
          const [reconciledRequestRun, durableConversation] = await Promise.all(
            [
              loadRequestRun(activeRequest.requestId),
              loadConversation(conversationId),
            ],
          )
          if (
            reconciledRequestRun &&
            reconciledRequestRun.conversation_id !== conversationId
          ) {
            return
          }

          // A 204 means there is no active transport to reattach to. Product
          // state and durable history are authoritative even when a terminal
          // stream event was lost or the producer disappeared.
          clearActiveRequest(activeRequest)
          requestIdRef.current = null
          unavailableReconnectRef.current = null
          queryClient.setQueryData(
            ["conversation", conversationId],
            durableConversation,
          )
          setMessages(toUIMessages(durableConversation.messages))
          return
        }
        await queryClient.invalidateQueries({
          queryKey: ["conversation", conversationId],
        })
      } catch {
        // useChat owns reconnect transport errors. Status/history refetch on a
        // later visit remains the durable fallback for validation failures.
      }
    })()
  }, [
    conversationId,
    conversationQuery.data,
    queryClient,
    resumeStream,
    setMessages,
    status,
  ])

  useEffect(() => {
    if (
      !conversationId ||
      !(conversationQuery.error instanceof ConversationLoadError) ||
      conversationQuery.error.status !== 404
    ) {
      return
    }

    if (localStorage.getItem(CONVERSATION_KEY) === conversationId) {
      localStorage.removeItem(CONVERSATION_KEY)
    }
    localStorage.removeItem(REQUEST_KEY)
    localStorage.removeItem(ACTIVE_REQUEST_KEY)
    hydratedConversationRef.current = null
    if (status === "ready") setMessages([])
    onConversationUnavailable?.()
  }, [
    conversationId,
    conversationQuery.error,
    onConversationUnavailable,
    setMessages,
    status,
  ])

  const historyError =
    conversationQuery.error && conversationQuery.error.status !== 404
      ? new Error("当前会话加载失败，请稍后重试。")
      : undefined

  return {
    ...chat,
    cancelRequest,
    currentConversation: conversationQuery.data,
    error: chat.error ?? historyError,
    isLoadingHistory: Boolean(conversationId) && conversationQuery.isPending,
  }
}
