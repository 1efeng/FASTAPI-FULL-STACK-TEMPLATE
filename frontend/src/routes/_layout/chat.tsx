import { createFileRoute } from "@tanstack/react-router"
import type { ChatStatus } from "ai"
import { useEffect, useState } from "react"
import { z } from "zod"

import {
  Conversation,
  ConversationContent,
} from "@/components/ai-elements/conversation"
import {
  PromptInput,
  PromptInputFooter,
  PromptInputProvider,
  PromptInputSubmit,
  PromptInputTextarea,
  usePromptInputController,
} from "@/components/ai-elements/prompt-input"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { useChatNavigation } from "@/features/chat/chat-navigation-context"
import { ChatMessage } from "@/features/chat/components/chat-message"
import { useProductChat } from "@/features/chat/use-product-chat"

const CONVERSATION_KEY = "travel_agent_conversation_id"
const chatSearchSchema = z.object({
  conversation: z.string().uuid().optional().catch(undefined),
})

export const Route = createFileRoute("/_layout/chat")({
  component: ChatPage,
  validateSearch: chatSearchSchema,
  head: () => ({ meta: [{ title: "行伴 · AI 旅行助手" }] }),
})

function Submit({
  status,
  onStop,
}: {
  status: ChatStatus
  onStop: () => void
}) {
  const { textInput } = usePromptInputController()
  const active =
    textInput.value.trim().length > 0 ||
    status === "submitted" ||
    status === "streaming"
  return (
    <PromptInputSubmit
      className="size-9 rounded-full bg-[#4d6bfe] text-white hover:bg-[#405ce8] disabled:opacity-40"
      disabled={!active}
      onStop={onStop}
      size="icon-sm"
      status={status}
      variant="default"
    />
  )
}

function ChatPage() {
  const { conversation } = Route.useSearch()
  const navigate = Route.useNavigate()
  const { setNavigationLocked } = useChatNavigation()
  const [copied, setCopied] = useState<string | null>(null)
  const {
    messages,
    sendMessage,
    status,
    cancelRequest,
    currentConversation,
    isLoadingHistory,
  } = useProductChat({
    conversationId: conversation,
    onConversationChange: (id) => {
      localStorage.setItem(CONVERSATION_KEY, id)
      void navigate({ search: { conversation: id }, replace: true })
    },
    onConversationUnavailable: () => {
      void navigate({ search: {}, replace: true })
    },
  })
  const streaming = status === "submitted" || status === "streaming"
  const empty = !isLoadingHistory && messages.length === 0
  useEffect(() => {
    setNavigationLocked(streaming)
    return () => setNavigationLocked(false)
  }, [setNavigationLocked, streaming])
  const submit = (text: string) => {
    if (text.trim() && !streaming && !isLoadingHistory)
      sendMessage({ text: text.trim() })
  }
  const composer = (
    <PromptInput
      className="w-full rounded-[25px] border border-[#e3e5e8] bg-white shadow-[0_14px_45px_rgba(31,35,48,0.09),0_2px_8px_rgba(31,35,48,0.04)] focus-within:border-[#d4d8e0] focus-within:shadow-[0_16px_50px_rgba(31,35,48,0.12)]"
      onSubmit={(m) => submit(m.text)}
    >
      <PromptInputTextarea
        className="min-h-[72px] px-5 pt-4 text-base leading-7 md:text-base placeholder:text-[#a7acb5]"
        disabled={streaming || isLoadingHistory}
        placeholder="给行伴发送消息"
      />
      <PromptInputFooter className="min-h-12 px-3 pb-3 pt-0">
        <div className="ml-auto">
          <Submit onStop={() => void cancelRequest()} status={status} />
        </div>
      </PromptInputFooter>
    </PromptInput>
  )
  return (
    <div className="flex h-full min-h-0 bg-background">
      <section className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 px-3 sm:px-5">
          <SidebarTrigger className="text-muted-foreground" />
          <p className="min-w-0 flex-1 truncate text-sm font-semibold">
            {currentConversation?.title ?? "新的对话"}
          </p>
        </header>
        <Conversation className="min-h-0 flex-1">
          <ConversationContent className={`mx-auto w-full max-w-[780px] px-5 sm:px-8 ${empty ? "h-full" : "pb-80 pt-8"}`}>
            {empty ? (
              <div className="relative -top-[4vh] flex h-full w-full flex-col items-center justify-center">
                <div className="mb-10 w-full text-center">
                  <h1 className="text-[24px] font-semibold tracking-[-0.02em] text-[#17181c]">
                    有什么旅行问题我能帮你的吗？
                  </h1>
                </div>
                <PromptInputProvider>{composer}</PromptInputProvider>
              </div>
            ) : (
              messages.map((message) => (
                <ChatMessage
                  copiedMessageId={copied}
                  isLastAssistant={
                    message.role === "assistant" &&
                    message.id === messages[messages.length - 1]?.id
                  }
                  isStreaming={streaming}
                  key={message.id}
                  message={message}
                  onCopy={(id, text) => {
                    void navigator.clipboard.writeText(text)
                    setCopied(id)
                  }}
                />
              ))
            )}
          </ConversationContent>
        </Conversation>
        {!empty && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-background via-background via-80% to-transparent px-5 pb-6 pt-12">
            <div className="pointer-events-auto mx-auto w-full max-w-[780px]">
              <PromptInputProvider>{composer}</PromptInputProvider>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
