import { HumanMessage, type BaseMessage } from "@langchain/core/messages"
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

const THREAD_STORAGE_KEY = "agent101.chat.threadId"

function newThreadId() {
  return crypto.randomUUID()
}

function initialThreadId() {
  const stored = sessionStorage.getItem(THREAD_STORAGE_KEY)
  if (stored) return stored
  const threadId = newThreadId()
  sessionStorage.setItem(THREAD_STORAGE_KEY, threadId)
  return threadId
}

function apiBaseUrl() {
  const configured = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "")
  const origin = configured || window.location.origin
  return `${origin}/api/v1`
}

const authenticatedFetch: typeof fetch = async (input, init) => {
  const headers = new Headers(init?.headers)
  const token = localStorage.getItem("access_token")
  if (token) headers.set("Authorization", `Bearer ${token}`)
  return window.fetch(input, { ...init, headers })
}

function activeRunStorageKey(threadId: string) {
  return `agent101.chat.activeRun.${threadId}`
}

interface ChatRuntimeProps {
  threadId: string
  sidebarCollapsed: boolean
  onNewChat: () => void
  onToggleSidebar: () => void
}

function ChatRuntime({
  threadId,
  sidebarCollapsed,
  onNewChat,
  onToggleSidebar,
}: ChatRuntimeProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [controlError, setControlError] = useState<string | null>(null)
  const stream = useStreamContext<ChatState>()

  const latestTool = stream.toolCalls.at(-1)
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
  }, [stream.messages.length, stream.toolCalls.length, stream.isLoading])

  const stopRun = async () => {
    setControlError(null)
    const runId = sessionStorage.getItem(activeRunStorageKey(threadId))
    try {
      // HttpAgentServerAdapter can attach auth to protocol requests, but the
      // SDK's separate runs.cancel client does not inherit those headers for a
      // custom adapter. Cancel the same standard REST route with auth first,
      // then only disconnect the protocol stream locally.
      if (runId) {
        const response = await authenticatedFetch(
          `${apiBaseUrl()}/threads/${threadId}/runs/${runId}/cancel?wait=0&action=interrupt`,
          { method: "POST" },
        )
        if (!response.ok && response.status !== 404) {
          throw new Error(`Cancel failed with ${response.status}`)
        }
      }
      await stream.stop({ cancel: false })
      sessionStorage.removeItem(activeRunStorageKey(threadId))
    } catch (error) {
      setControlError(error instanceof Error ? error.message : "停止运行失败")
    }
  }

  const handleNewChat = async () => {
    if (stream.isLoading) {
      await stopRun()
      if (stream.isLoading) return
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
          {(stream.error || controlError) && (
            <div
              className="mx-auto w-full max-w-3xl px-4 pb-4 md:px-6"
              role="alert"
            >
              <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                {controlError ?? "对话请求失败，请稍后重试。"}
              </div>
            </div>
          )}
        </div>

        <ChatComposer
          isGenerating={stream.isLoading}
          onStop={() => void stopRun()}
          onSubmit={(text) =>
            void stream.submit({ messages: [new HumanMessage(text)] })
          }
        />
      </main>
    </div>
  )
}

interface ChatSessionProps extends Omit<ChatRuntimeProps, "threadId"> {
  threadId: string
}

function ChatSession({ threadId, ...props }: ChatSessionProps) {
  const transport = useMemo(
    () =>
      new HttpAgentServerAdapter({
        apiUrl: apiBaseUrl(),
        threadId,
        fetch: authenticatedFetch,
        paths: {
          commands: `/threads/${threadId}/commands`,
          stream: `/threads/${threadId}/stream`,
          state: `/threads/${threadId}/state`,
        },
      }),
    [threadId],
  )

  return (
    <StreamProvider<ChatState>
      onCompleted={() => {
        sessionStorage.removeItem(activeRunStorageKey(threadId))
      }}
      onCreated={({ runId }) => {
        sessionStorage.setItem(activeRunStorageKey(threadId), runId)
      }}
      transport={transport}
    >
      <ChatRuntime threadId={threadId} {...props} />
    </StreamProvider>
  )
}

export function ChatPage() {
  const [threadId, setThreadId] = useState(initialThreadId)
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
