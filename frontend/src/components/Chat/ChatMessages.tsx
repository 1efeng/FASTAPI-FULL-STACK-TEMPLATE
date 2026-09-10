import type { BaseMessage } from "@langchain/core/messages"

interface ChatMessagesProps {
  messages: BaseMessage[]
}

export function ChatMessages({ messages }: ChatMessagesProps) {
  const visibleMessages = messages.filter(
    (message) => message.type === "human" || message.type === "ai",
  )

  if (visibleMessages.length === 0) {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center px-6 text-center">
        <div className="mb-3 flex size-10 items-center justify-center rounded-xl border bg-background shadow-sm">
          <span className="text-lg">✦</span>
        </div>
        <h1 className="text-xl font-medium tracking-tight">有什么可以帮你？</h1>
        <p className="mt-2 text-sm text-muted-foreground">输入消息开始对话。</p>
      </div>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-8 md:px-6 md:py-10">
      {visibleMessages.map((message, index) => {
        const isUser = message.type === "human"
        return (
          <article
            className={
              isUser
                ? "ml-auto max-w-[85%] rounded-2xl bg-muted px-4 py-2.5 text-sm leading-6"
                : "mr-auto w-full text-sm leading-7"
            }
            key={message.id ?? `${message.type}-${index}`}
          >
            <div className="whitespace-pre-wrap break-words">{message.text}</div>
          </article>
        )
      })}
    </div>
  )
}
