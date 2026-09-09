import { createFileRoute } from "@tanstack/react-router"

import { ChatPage } from "@/components/Chat/ChatPage"

export const Route = createFileRoute("/_layout/")({
  component: ChatPage,
  head: () => ({
    meta: [
      {
        title: "Chat - Agent Platform",
      },
    ],
  }),
})
