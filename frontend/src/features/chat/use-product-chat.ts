import { useChat } from "@ai-sdk/react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { DefaultChatTransport, type UIMessage } from "ai"
import { useCallback, useEffect, useMemo, useRef } from "react"
import { apiFetch } from "@/lib/auth"
import {
  clearActiveRequest,
  clearActiveRequestForConversation,
  readActiveRequest,
  saveActiveRequest,
} from "./active-request-storage"
import {
  type ConversationDetail,
  ConversationLoadError,
  loadConversation,
  toUIMessages,
} from "./conversation-api"

export type ProductUIMessage = UIMessage

type UseProductChatOptions = {
  conversationId?: string
  enableWebSearch?: boolean
  enableThinking?: boolean
  onConversationChange?: (conversationId: string) => void
  onConversationUnavailable?: () => void
}

type ReconcileState = {
  hydratedConversationId: string | null
  attemptedRequestKey: string | null
  unavailableRequestId: string | null
  previousConversationId: string | undefined
}

function productChatFetch(
  getConversationId: () => string | undefined,
  onConversationId?: (conversationId: string) => void,
  onRequestId?: (requestId: string) => void,
  onReconnectUnavailable?: () => void,
): typeof globalThis.fetch {
  return async (input, init) => {
    const response = await apiFetch(input, init)
    if (init?.method === "GET" && response.status === 204) {
      onReconnectUnavailable?.()
    }
    const responseConversationId = response.headers.get("X-Conversation-Id")
    const requestId = response.headers.get("X-Request-Id")
    const currentConversationId = responseConversationId ?? getConversationId()
    if (requestId && currentConversationId) {
      saveActiveRequest(requestId, currentConversationId)
      onRequestId?.(requestId)
    }
    if (responseConversationId) {
      onConversationId?.(responseConversationId)
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
  enableWebSearch = true,
  enableThinking = true,
  onConversationChange,
  onConversationUnavailable,
}: UseProductChatOptions = {}) {
  const queryClient = useQueryClient()
  const requestIdRef = useRef<string | null>(null)
  const conversationIdRef = useRef(conversationId)
  const reconcileRef = useRef<ReconcileState>({
    hydratedConversationId: null,
    attemptedRequestKey: null,
    unavailableRequestId: null,
    previousConversationId: conversationId,
  })

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
          (resolvedConversationId) => {
            if (resolvedConversationId !== conversationIdRef.current) {
              conversationIdRef.current = resolvedConversationId
              reconcileRef.current.hydratedConversationId =
                resolvedConversationId
              onConversationChange?.(resolvedConversationId)
              void queryClient.invalidateQueries({
                queryKey: ["conversations"],
              })
            }
          },
          (requestId) => {
            requestIdRef.current = requestId
          },
          () => {
            reconcileRef.current.unavailableRequestId = requestIdRef.current
          },
        ),
        prepareSendMessagesRequest: async ({ body, headers, messages, id }) => {
          const resolvedConversationId = conversationIdRef.current ?? null
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
              enable_web_search: enableWebSearch,
              enable_thinking: enableThinking,
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
            },
          }
        },
      }),
    [enableThinking, enableWebSearch, onConversationChange, queryClient],
  )

  const chat = useChat<ProductUIMessage>({
    transport,
    onFinish: ({ isAbort, isDisconnect }) => {
      const currentConversationId = conversationIdRef.current
      // Browser refresh/navigation aborts only the subscriber. Preserve the
      // active request hint so the next page instance can reconnect.
      if (!currentConversationId || isAbort || isDisconnect) return
      const activeRequest = readActiveRequest(currentConversationId)
      if (activeRequest) clearActiveRequest(activeRequest)
      requestIdRef.current = null
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

    const response = await apiFetch(
      `/api/v1/chat/requests/${requestId}/cancel`,
      {
        method: "POST",
      },
    )
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
    const previousConversationId = reconcileRef.current.previousConversationId
    if (previousConversationId !== conversationId) {
      if (previousConversationId) {
        clearActiveRequestForConversation(previousConversationId)
      }
      reconcileRef.current.hydratedConversationId = null
      reconcileRef.current.attemptedRequestKey = null
      reconcileRef.current.unavailableRequestId = null
      requestIdRef.current = null
      if (conversationId === undefined) setMessages([])
    }
    reconcileRef.current.previousConversationId = conversationId
  }, [conversationId, setMessages])

  useEffect(() => {
    if (!conversationId || !conversationQuery.data) return

    if (
      reconcileRef.current.hydratedConversationId !== conversationId &&
      status === "ready"
    ) {
      setMessages(toUIMessages(conversationQuery.data.messages))
      reconcileRef.current.hydratedConversationId = conversationId
    }

    const activeRequest = readActiveRequest(conversationId)
    if (!activeRequest) return

    const attemptKey = `${conversationId}:${activeRequest.requestId}`
    if (
      reconcileRef.current.attemptedRequestKey === attemptKey ||
      reconcileRef.current.hydratedConversationId !== conversationId ||
      status !== "ready"
    ) {
      return
    }
    reconcileRef.current.attemptedRequestKey = attemptKey
    requestIdRef.current = activeRequest.requestId
    reconcileRef.current.unavailableRequestId = null

    void (async () => {
      const reconcileDurable = async () => {
        const durableConversation = await loadConversation(conversationId)
        clearActiveRequest(activeRequest)
        requestIdRef.current = null
        reconcileRef.current.unavailableRequestId = null
        queryClient.setQueryData(
          ["conversation", conversationId],
          durableConversation,
        )
        setMessages(toUIMessages(durableConversation.messages))
      }
      try {
        await resumeStream()
        if (
          reconcileRef.current.unavailableRequestId === activeRequest.requestId
        ) {
          // A 204 means there is no active transport to reattach to. Product
          // state and durable history are authoritative when the stream ended
          // before the browser received its terminal event.
          await reconcileDurable()
          return
        }
        await queryClient.invalidateQueries({
          queryKey: ["conversation", conversationId],
        })
      } catch {
        // Reconnect failures fall back to durable history so the UI never stays
        // half-hydrated with a stale active-request hint.
        await reconcileDurable()
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

    clearActiveRequestForConversation(conversationId)
    reconcileRef.current.hydratedConversationId = null
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
