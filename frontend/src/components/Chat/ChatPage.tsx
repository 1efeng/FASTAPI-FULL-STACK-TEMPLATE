import { useChat } from "@ai-sdk/react"
import {
  DefaultChatTransport,
  getToolName,
  isToolUIPart,
  type ChatStatus,
  type UIMessage,
} from "ai"
import { MessageSquarePlus } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { ChatActivity } from "@/components/Chat/ChatActivity"
import { ChatComposer } from "@/components/Chat/ChatComposer"
import { ChatMessages } from "@/components/Chat/ChatMessages"
import { ChatThreadSidebar } from "@/components/Chat/ChatThreadSidebar"
import { Button } from "@/components/ui/button"

function newThreadId() {
  return crypto.randomUUID()
}

function apiUrl(path: string) {
  const base = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "")
  return `${base}${path}`
}

const chatTransport = new DefaultChatTransport({
  api: apiUrl("/api/v1/chat/stream"),
  headers: () => {
    const token = localStorage.getItem("access_token")
    return token ? { Authorization: `Bearer ${token}` } : {}
  },
})

function getActivityLabel(messages: UIMessage[], status: ChatStatus) {
  if (status === "submitted") return "正在思考…"
  if (status !== "streaming") return null

  const assistant = [...messages]
    .reverse()
    .find((message) => message.role === "assistant")

  if (!assistant) return "正在思考…"

  const latestTool = [...assistant.parts]
    .reverse()
    .find((part) => isToolUIPart(part))

  if (latestTool && isToolUIPart(latestTool)) {
    if (
      latestTool.state === "input-streaming" ||
      latestTool.state === "input-available"
    ) {
      return `正在使用 ${getToolName(latestTool)}…`
    }
    if (latestTool.state === "output-available") {
      return "正在整理结果…"
    }
  }

  const hasText = assistant.parts.some(
    (part) => part.type === "text" && part.text.length > 0,
  )
  return hasText ? null : "正在思考…"
}

interface ChatSessionProps {
  threadId: string
  sidebarCollapsed: boolean
  onNewChat: () => void
  onToggleSidebar: () => void
}

function ChatSession({
  threadId,
  sidebarCollapsed,
  onNewChat,
  onToggleSidebar,
}: ChatSessionProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const { error, messages, sendMessage, status, stop } = useChat({
    id: threadId,
    transport: chatTransport,
  })
  const activityLabel = getActivityLabel(messages, status)

  useEffect(() => {
    const viewport = scrollRef.current
    if (!viewport) return
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" })
  }, [activityLabel, messages])

  const handleNewChat = () => {
    void stop()
    onNewChat()
  }

  return (
    <div className="flex h-svh min-h-0 min-w-0 overflow-hidden bg-background">
      <ChatThreadSidebar
        collapsed={sidebarCollapsed}
        onNewChat={handleNewChat}
        onToggle={onToggleSidebar}
      />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-background">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b bg-background/95 px-3 backdrop-blur md:hidden">
          <h1 className="min-w-0 flex-1 truncate text-sm font-medium">Agent Platform</h1>
          <Button
            aria-label="新建对话"
            className="size-8"
            onClick={handleNewChat}
            size="icon"
            type="button"
            variant="ghost"
          >
            <MessageSquarePlus className="size-4" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto" ref={scrollRef}>
          <ChatMessages messages={messages} />
          <ChatActivity label={activityLabel} />
          {error && (
            <div className="mx-auto w-full max-w-3xl px-4 pb-4 md:px-6" role="alert">
              <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                对话请求失败，请稍后重试。
              </div>
            </div>
          )}
        </div>

        <ChatComposer
          onStop={() => void stop()}
          onSubmit={(text) => void sendMessage({ text })}
          status={status}
        />
      </main>
    </div>
  )
}

export function ChatPage() {
  const [threadId, setThreadId] = useState(newThreadId)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  return (
    <ChatSession
      key={threadId}
      onNewChat={() => setThreadId(newThreadId())}
      onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
      sidebarCollapsed={sidebarCollapsed}
      threadId={threadId}
    />
  )
}
