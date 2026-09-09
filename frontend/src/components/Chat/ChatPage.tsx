import { MessageSquarePlus } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { ChatActivity } from "@/components/Chat/ChatActivity"
import { ChatComposer } from "@/components/Chat/ChatComposer"
import { ChatMessages } from "@/components/Chat/ChatMessages"
import { ChatThreadSidebar } from "@/components/Chat/ChatThreadSidebar"
import { Button } from "@/components/ui/button"
import { useChatStream } from "@/hooks/useChatStream"

function newThreadId() {
  return crypto.randomUUID()
}

export function ChatPage() {
  const [threadId, setThreadId] = useState(newThreadId)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const {
    activityLabel,
    error,
    messages,
    reset,
    sendMessage,
    status,
    stop,
  } = useChatStream()

  useEffect(() => {
    const viewport = scrollRef.current
    if (!viewport) return
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" })
  }, [activityLabel, messages])

  const handleNewChat = () => {
    reset()
    setThreadId(newThreadId())
  }

  return (
    <div className="flex h-svh min-h-0 min-w-0 overflow-hidden bg-background">
      <ChatThreadSidebar
        collapsed={sidebarCollapsed}
        onNewChat={handleNewChat}
        onToggle={() => setSidebarCollapsed((value) => !value)}
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
                {error}
              </div>
            </div>
          )}
        </div>

        <ChatComposer
          onStop={stop}
          onSubmit={(text) => void sendMessage(threadId, text)}
          status={status}
        />
      </main>
    </div>
  )
}
