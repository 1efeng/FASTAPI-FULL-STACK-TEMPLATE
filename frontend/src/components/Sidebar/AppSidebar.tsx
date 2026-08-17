import { useNavigate, useRouterState } from "@tanstack/react-router"
import { useCallback } from "react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  useSidebar,
} from "@/components/ui/sidebar"
import { useChatNavigation } from "@/features/chat/chat-navigation-context"
import { ConversationHistory } from "@/features/chat/conversation-history"
import useAuth from "@/hooks/useAuth"
import { cn } from "@/lib/utils"
import { User } from "./User"

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const navigate = useNavigate()
  const { isMobile, setOpenMobile } = useSidebar()
  const { isNavigationLocked, startNewConversation } = useChatNavigation()
  const location = useRouterState({ select: (state) => state.location })
  const isChat = location.pathname === "/chat"
  const activeConversationId =
    location.pathname === "/chat"
      ? (location.search as { conversation?: string }).conversation
      : undefined

  const closeMobileSidebar = useCallback(() => {
    if (isMobile) setOpenMobile(false)
  }, [isMobile, setOpenMobile])

  const handleNewConversation = useCallback(() => {
    startNewConversation()
    closeMobileSidebar()
  }, [closeMobileSidebar, startNewConversation])

  const selectConversation = useCallback(
    (conversationId: string) => {
      closeMobileSidebar()
      void navigate({
        to: "/chat",
        search: { conversation: conversationId },
        replace: true,
      })
    },
    [closeMobileSidebar, navigate],
  )

  return (
    <Sidebar className={cn(isChat && "chat-sidebar")} collapsible="offcanvas">
      <SidebarContent className="min-h-0 overflow-hidden pt-5">
        <ConversationHistory
          activeConversationId={activeConversationId}
          disabled={isNavigationLocked}
          onNewConversation={handleNewConversation}
          onSelectConversation={selectConversation}
        />
      </SidebarContent>
      <SidebarFooter className="mt-auto border-t border-sidebar-border/60 px-3 pb-1 pt-2">
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
