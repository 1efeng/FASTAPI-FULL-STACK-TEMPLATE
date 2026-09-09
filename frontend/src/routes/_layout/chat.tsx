import { createFileRoute } from "@tanstack/react-router"
import type { ChatStatus } from "ai"
import { Brain, Globe } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { z } from "zod"

import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation"
import {
  PromptInput,
  PromptInputButton,
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
  const [webSearchEnabled, setWebSearchEnabled] = useState(true)
  const [thinkingEnabled, setThinkingEnabled] = useState(true)
  const onConversationChange = useCallback(
    (id: string) => {
      void navigate({ search: { conversation: id }, replace: true })
    },
    [navigate],
  )
  const onConversationUnavailable = useCallback(() => {
    void navigate({ search: {}, replace: true })
  }, [navigate])
  const {
    messages,
    sendMessage,
    status,
    cancelRequest,
    currentConversation,
    error,
    isLoadingHistory,
  } = useProductChat({
    conversationId: conversation,
    enableWebSearch: webSearchEnabled,
    enableThinking: thinkingEnabled,
    onConversationChange,
    onConversationUnavailable,
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
        <PromptInputButton
          aria-pressed={webSearchEnabled}
          className={
            webSearchEnabled
              ? "rounded-full bg-[#eef2ff] text-[#405ce8] hover:bg-[#e1e7ff] hover:text-[#304bd0]"
              : "rounded-full text-[#7b818c] hover:bg-[#f1f2f4] hover:text-[#4d5562]"
          }
          disabled={streaming || isLoadingHistory}
          onClick={() => setWebSearchEnabled((enabled) => !enabled)}
          size="sm"
          title={webSearchEnabled ? "已开启智能联网" : "已关闭智能联网"}
          variant="ghost"
        >
          <Globe className="size-4" />
          <span>智能联网</span>
        </PromptInputButton>
        <PromptInputButton
          aria-pressed={thinkingEnabled}
          className={
            thinkingEnabled
              ? "rounded-full bg-[#eef2ff] text-[#405ce8] hover:bg-[#e1e7ff] hover:text-[#304bd0]"
              : "rounded-full text-[#7b818c] hover:bg-[#f1f2f4] hover:text-[#4d5562]"
          }
          disabled={streaming || isLoadingHistory}
          onClick={() => setThinkingEnabled((enabled) => !enabled)}
          size="sm"
          title={thinkingEnabled ? "已开启思考" : "已关闭思考"}
          variant="ghost"
        >
          <Brain className="size-4" />
          <span>思考</span>
        </PromptInputButton>
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
          <p className="min-w-0 flex-1 truncate text-sm">
            {currentConversation?.title ?? "新的对话"}
          </p>
        </header>
        <Conversation className="min-h-0 flex-1">
          <ConversationContent
            className={`mx-auto w-full max-w-[900px] px-6 sm:px-8 ${empty ? "h-full" : "pb-48 pt-8"}`}
          >
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
                  showReasoning={thinkingEnabled}
                />
              ))
            )}
            {error && (
              <div
                className="mt-4 rounded-lg border border-destructive/25 bg-destructive/5 px-4 py-3 text-sm text-destructive"
                role="alert"
              >
                {error.message || "请求处理失败，请稍后重试。"}
              </div>
            )}
          </ConversationContent>
          <ConversationScrollButton className="bottom-40 border-[#e3e5e8] bg-white text-muted-foreground shadow-[0_2px_8px_rgba(31,35,48,0.08)] hover:bg-[#f1f2f4] hover:text-foreground dark:bg-background dark:hover:bg-muted dark:text-muted-foreground" />
        </Conversation>
        {!empty && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-background via-background via-80% to-transparent pb-6 pt-12">
            <div className="pointer-events-auto mx-auto w-full max-w-[920px] px-6 sm:px-8">
              <PromptInputProvider>{composer}</PromptInputProvider>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
