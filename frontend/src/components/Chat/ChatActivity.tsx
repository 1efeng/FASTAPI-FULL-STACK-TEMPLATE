import { LoaderCircle } from "lucide-react"

interface ChatActivityProps {
  label?: string | null
}

export function ChatActivity({ label }: ChatActivityProps) {
  if (!label) return null

  return (
    <div
      aria-live="polite"
      className="mx-auto flex w-full max-w-3xl items-center gap-2 px-4 pb-4 text-sm text-muted-foreground md:px-6"
      role="status"
    >
      <LoaderCircle className="size-4 animate-spin" />
      <span>{label}</span>
    </div>
  )
}
