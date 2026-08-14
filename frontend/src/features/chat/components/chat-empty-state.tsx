import type { ReactNode } from "react"

import { ConversationEmptyState } from "@/components/ai-elements/conversation"

export function ChatEmptyState({ children }: { children?: ReactNode }) {
  return (
    <ConversationEmptyState className="flex h-full w-full max-w-none items-center justify-center gap-0 px-5 pb-[8vh] sm:px-8">
      {children}
    </ConversationEmptyState>
  )
}

