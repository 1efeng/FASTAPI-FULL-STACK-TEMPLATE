import { useCallback, useRef, useState } from "react"

export type ChatRole = "user" | "assistant"

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
}

export type ChatStatus = "ready" | "submitted" | "streaming" | "error"

type AgentEvent =
  | { type: "run.started"; runId?: string }
  | { type: "message.delta"; delta: string }
  | { type: "tool.started"; name: string }
  | { type: "tool.completed"; name: string }
  | { type: "approval.required" }
  | { type: "run.completed" }
  | { type: "run.failed"; message?: string }

function apiUrl(path: string) {
  const base = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "")
  return `${base}${path}`
}

function parseEvent(block: string): AgentEvent | null {
  let eventType = "message"
  const dataLines: string[] = []

  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) eventType = line.slice(6).trim()
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart())
  }

  if (dataLines.length === 0) return null

  try {
    const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>
    return { type: eventType, ...data } as AgentEvent
  } catch {
    if (eventType === "message.delta") {
      return { type: "message.delta", delta: dataLines.join("\n") }
    }
    return null
  }
}

export function useChatStream() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [status, setStatus] = useState<ChatStatus>("ready")
  const [activityLabel, setActivityLabel] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const appendAssistantDelta = useCallback((assistantId: string, delta: string) => {
    setMessages((current) => {
      const existing = current.find((message) => message.id === assistantId)
      if (!existing) {
        return [...current, { id: assistantId, role: "assistant", content: delta }]
      }
      return current.map((message) =>
        message.id === assistantId
          ? { ...message, content: `${message.content}${delta}` }
          : message,
      )
    })
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setMessages([])
    setStatus("ready")
    setActivityLabel(null)
    setError(null)
  }, [])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setStatus("ready")
    setActivityLabel(null)
  }, [])

  const sendMessage = useCallback(
    async (threadId: string, text: string) => {
      const value = text.trim()
      if (!value || status === "submitted" || status === "streaming") return

      const userMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: value,
      }
      const assistantId = crypto.randomUUID()
      const controller = new AbortController()
      abortRef.current = controller

      setMessages((current) => [...current, userMessage])
      setStatus("submitted")
      setActivityLabel("正在思考…")
      setError(null)

      try {
        const token = localStorage.getItem("access_token")
        const response = await fetch(apiUrl("/api/v1/chat/stream"), {
          method: "POST",
          headers: {
            Accept: "text/event-stream",
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ message: value, thread_id: threadId }),
          signal: controller.signal,
        })

        if (!response.ok) {
          if (response.status === 404) {
            throw new Error("Chat 后端尚未接入 /api/v1/chat/stream")
          }
          throw new Error(`Chat request failed (${response.status})`)
        }
        if (!response.body) throw new Error("Chat stream is unavailable")

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ""

        while (true) {
          const { done, value: chunk } = await reader.read()
          buffer += decoder.decode(chunk, { stream: !done })

          const blocks = buffer.split(/\r?\n\r?\n/)
          buffer = blocks.pop() ?? ""

          for (const block of blocks) {
            const event = parseEvent(block)
            if (!event) continue

            switch (event.type) {
              case "run.started":
                setActivityLabel("正在思考…")
                break
              case "message.delta":
                setStatus("streaming")
                setActivityLabel(null)
                appendAssistantDelta(assistantId, event.delta)
                break
              case "tool.started":
                setActivityLabel(`正在使用 ${event.name}…`)
                break
              case "tool.completed":
                setActivityLabel("正在整理结果…")
                break
              case "approval.required":
                setActivityLabel("等待确认…")
                break
              case "run.completed":
                setStatus("ready")
                setActivityLabel(null)
                break
              case "run.failed":
                throw new Error(event.message || "Agent run failed")
            }
          }

          if (done) break
        }

        setStatus("ready")
        setActivityLabel(null)
      } catch (caught) {
        if (controller.signal.aborted) return
        setStatus("error")
        setActivityLabel(null)
        setError(caught instanceof Error ? caught.message : "Chat request failed")
      } finally {
        if (abortRef.current === controller) abortRef.current = null
      }
    },
    [appendAssistantDelta, status],
  )

  return {
    activityLabel,
    error,
    messages,
    reset,
    sendMessage,
    status,
    stop,
  }
}
