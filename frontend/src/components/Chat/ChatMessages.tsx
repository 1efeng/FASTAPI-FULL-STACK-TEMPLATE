import { getToolName, isToolUIPart, type UIMessage } from "ai"

interface ChatMessagesProps {
  messages: UIMessage[]
}

function formatToolState(state: string) {
  switch (state) {
    case "input-streaming":
      return "正在准备参数"
    case "input-available":
      return "正在执行"
    case "output-available":
      return "已完成"
    case "output-error":
      return "执行失败"
    default:
      return state
  }
}

export function ChatMessages({ messages }: ChatMessagesProps) {
  if (messages.length === 0) {
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
      {messages.map((message) => (
        <article
          className={
            message.role === "user"
              ? "ml-auto max-w-[85%] rounded-2xl bg-muted px-4 py-2.5 text-sm leading-6"
              : "mr-auto w-full text-sm leading-7"
          }
          key={message.id}
        >
          <div className="space-y-3">
            {message.parts.map((part, index) => {
              if (part.type === "text") {
                return (
                  <div
                    className="whitespace-pre-wrap break-words"
                    key={`${message.id}-text-${index}`}
                  >
                    {part.text}
                  </div>
                )
              }

              if (isToolUIPart(part)) {
                return (
                  <div
                    className="rounded-lg border bg-muted/30 px-3 py-2 text-xs text-muted-foreground"
                    key={`${message.id}-tool-${index}`}
                  >
                    <span className="font-medium text-foreground">
                      {getToolName(part)}
                    </span>
                    <span className="ml-2">{formatToolState(part.state)}</span>
                  </div>
                )
              }

              return null
            })}
          </div>
        </article>
      ))}
    </div>
  )
}
