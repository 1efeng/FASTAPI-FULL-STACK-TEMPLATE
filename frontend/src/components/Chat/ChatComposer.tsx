import { ArrowUp, Square } from "lucide-react"
import { useRef, useState } from "react"

import { Button } from "@/components/ui/button"

interface ChatComposerProps {
  isGenerating: boolean
  onStop: () => void
  onSubmit: (text: string) => void
}

export function ChatComposer({
  isGenerating,
  onStop,
  onSubmit,
}: ChatComposerProps) {
  const [value, setValue] = useState("")
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const canSubmit = value.trim().length > 0 && !isGenerating

  const submit = () => {
    if (!canSubmit) return
    onSubmit(value)
    setValue("")
    requestAnimationFrame(() => textareaRef.current?.focus())
  }

  return (
    <div
      className="shrink-0 bg-gradient-to-t from-background via-background/95 to-background/70 pt-2"
      style={{ paddingBottom: "max(1rem, env(safe-area-inset-bottom))" }}
    >
      <div className="mx-auto w-full max-w-3xl px-4 md:px-6">
        <div className="rounded-2xl border bg-background p-2 shadow-sm transition-shadow focus-within:shadow-md">
          <textarea
            aria-label="消息"
            className="max-h-48 min-h-12 w-full resize-none bg-transparent px-2 py-2 text-sm leading-6 outline-none placeholder:text-muted-foreground"
            onChange={(event) => setValue(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                submit()
              }
            }}
            placeholder="向 Agent 提问…"
            ref={textareaRef}
            rows={1}
            value={value}
          />
          <div className="flex items-center justify-end px-1 pb-1">
            {isGenerating ? (
              <Button
                aria-label="停止生成"
                className="size-8 rounded-full"
                onClick={onStop}
                size="icon"
                type="button"
              >
                <Square className="size-3.5 fill-current" />
              </Button>
            ) : (
              <Button
                aria-label="发送消息"
                className="size-8 rounded-full"
                disabled={!canSubmit}
                onClick={submit}
                size="icon"
                type="button"
              >
                <ArrowUp className="size-4" />
              </Button>
            )}
          </div>
        </div>
        <p className="mt-2 text-center text-[11px] text-muted-foreground">
          Agent 可能会出错，请核对重要信息。
        </p>
      </div>
    </div>
  )
}
