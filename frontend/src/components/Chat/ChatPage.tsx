import { type BaseMessage, HumanMessage } from "@langchain/core/messages"
import {
  HttpAgentServerAdapter,
  StreamProvider,
  useStreamContext,
} from "@langchain/react"
import { MessageSquarePlus } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { ChatActivity } from "@/components/Chat/ChatActivity"
import { ChatComposer } from "@/components/Chat/ChatComposer"
import { ChatMessages } from "@/components/Chat/ChatMessages"
import { ChatThreadSidebar } from "@/components/Chat/ChatThreadSidebar"
import { Button } from "@/components/ui/button"

interface ChatState {
  messages: BaseMessage[]
}

// The thread id is minted client-side and persisted for the browser session
// so a refresh re-attaches to the same thread instead of starting a new one.
const THREAD_STORAGE_KEY = "agent101.chat.threadId"

function newThreadId() {
  return crypto.randomUUID()
}

function currentThreadId() {
  const stored = sessionStorage.getItem(THREAD_STORAGE_KEY)
  if (stored) return stored
  const threadId = newThreadId()
  sessionStorage.setItem(THREAD_STORAGE_KEY, threadId)
  return threadId
}

function aegraBaseUrl() {
  return (import.meta.env.VITE_AEGRA_URL ?? "").replace(/\/$/, "")
}

// Aegra validates the same HS256 JWT that FastAPI issues, so forward the
// existing session token to the agent runtime on every request.
const authenticatedFetch: typeof fetch = async (input, init) => {
  const headers = new Headers(init?.headers)
  const token = localStorage.getItem("access_token")
  if (token) headers.set("Authorization", `Bearer ${token}`)
  return window.fetch(input, { ...init, headers })
}

interface ChatSessionProps {
  threadId: string
  sidebarCollapsed: boolean
  onNewChat: () => void
  onToggleSidebar: () => void
}

function ChatRuntime({
  sidebarCollapsed,
  onNewChat,
  onToggleSidebar,
}: Omit<ChatSessionProps, "threadId">) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const stream = useStreamContext<ChatState>()

  const latestTool = stream.toolCalls[stream.toolCalls.length - 1]
  const activityLabel = (() => {
    if (latestTool?.status === "running") return `正在使用 ${latestTool.name}…`
    if (stream.isLoading && latestTool?.status === "finished") {
      return "正在整理结果…"
    }
    if (stream.isLoading) return "正在思考…"
    return null
  })()

  useEffect(() => {
    const viewport = scrollRef.current
    if (!viewport) return
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" })
  })

  const handleNewChat = async () => {
    if (stream.isLoading) {
      // Leave the server-side run executing and just drop this client
      // connection; Aegra keeps the run alive and replays it on reload.
      await stream.disconnect()
    }
    onNewChat()
  }

  return (
    <div className="flex h-svh min-h-0 min-w-0 overflow-hidden bg-background">
      <ChatThreadSidebar
        collapsed={sidebarCollapsed}
        onNewChat={() => void handleNewChat()}
        onToggle={onToggleSidebar}
      />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-background">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b bg-background/95 px-3 backdrop-blur md:hidden">
          <h1 className="min-w-0 flex-1 truncate text-sm font-medium">
            Agent Platform
          </h1>
          <Button
            aria-label="新建对话"
            className="size-8"
            onClick={() => void handleNewChat()}
            size="icon"
            type="button"
            variant="ghost"
          >
            <MessageSquarePlus className="size-4" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto" ref={scrollRef}>
          <ChatMessages messages={stream.messages} />
          <ChatActivity label={activityLabel} />
          {stream.error ? (
            <div
              className="mx-auto w-full max-w-3xl px-4 pb-4 md:px-6"
              role="alert"
            >
              <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                {stream.error instanceof Error
                  ? stream.error.message
                  : String(stream.error)}
              </div>
            </div>
          ) : null}
        </div>

        <ChatComposer
          isGenerating={stream.isLoading}
          onStop={() => void stream.stop()}
          onSubmit={(text) =>
            void stream.submit({ messages: [new HumanMessage(text)] })
          }
        />
      </main>
    </div>
  )
}

function ChatSession({
  threadId,
  sidebarCollapsed,
  onNewChat,
  onToggleSidebar,
}: ChatSessionProps) {
  const transport = useMemo(
    () =>
      new HttpAgentServerAdapter({
        apiUrl: aegraBaseUrl(),
        threadId,
        fetch: authenticatedFetch,
        paths: {
          commands: `/threads/${threadId}/commands`,
          stream: `/threads/${threadId}/stream/events`,
          state: `/threads/${threadId}/state`,
        },
      }),
    [threadId],
  )

  // The SDK types assistantId as `never` on the custom-adapter branch even
  // though useStream forwards it to ThreadStream -> run.start, so the
  // union of provider props rejects our (assistantId + custom transport)
  // combination. Silence that upstream typing bug.
  return (
    // @ts-expect-error SDK CustomAdapterOptions types assistantId as never
    <StreamProvider<ChatState>
      assistantId="travel_planning"
      threadId={threadId}
      transport={transport}
    >
      <ChatRuntime
        onNewChat={onNewChat}
        onToggleSidebar={onToggleSidebar}
        sidebarCollapsed={sidebarCollapsed}
      />
    </StreamProvider>
  )
}

export function ChatPage() {
  const [threadId, setThreadId] = useState(currentThreadId)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  const startNewThread = () => {
    const nextThreadId = newThreadId()
    sessionStorage.setItem(THREAD_STORAGE_KEY, nextThreadId)
    setThreadId(nextThreadId)
  }

  return (
    <ChatSession
      key={threadId}
      onNewChat={startNewThread}
      onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
      sidebarCollapsed={sidebarCollapsed}
      threadId={threadId}
    />
  )
}
