import { MessageSquarePlus, PanelLeftClose, PanelLeftOpen } from "lucide-react"

import { Button } from "@/components/ui/button"
import useAuth from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

interface ChatThreadSidebarProps {
  collapsed: boolean
  onNewChat: () => void
  onToggle: () => void
}

export function ChatThreadSidebar({
  collapsed,
  onNewChat,
  onToggle,
}: ChatThreadSidebarProps) {
  const { user } = useAuth()

  return (
    <aside
      className={cn(
        "hidden h-svh shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground transition-[width] duration-200 md:flex",
        collapsed ? "w-14" : "w-64",
      )}
    >
      <div
        className={cn(
          "flex h-14 shrink-0 items-center px-2",
          collapsed ? "justify-center" : "gap-2",
        )}
      >
        {!collapsed && (
          <div className="min-w-0 flex-1 px-2 text-sm font-semibold tracking-tight">
            Agent Platform
          </div>
        )}
        <Button
          aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
          className="size-8 shrink-0 rounded-lg"
          onClick={onToggle}
          size="icon"
          type="button"
          variant="ghost"
        >
          {collapsed ? (
            <PanelLeftOpen className="size-4" />
          ) : (
            <PanelLeftClose className="size-4" />
          )}
        </Button>
      </div>

      {!collapsed && (
        <>
          <div className="px-2 pb-2">
            <Button
              className="h-9 w-full justify-start gap-2 rounded-lg px-2.5"
              onClick={onNewChat}
              type="button"
              variant="ghost"
            >
              <MessageSquarePlus className="size-[18px]" />
              新建对话
            </Button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
            <div className="mt-3">
              <p className="px-2 text-xs font-medium text-muted-foreground/80">
                对话
              </p>
              <p className="mt-2 px-2 text-xs text-muted-foreground">
                暂无历史对话
              </p>
            </div>
          </div>

          <div className="border-t px-3 py-3">
            <p className="truncate text-xs font-medium">
              {user?.full_name || user?.email || "当前用户"}
            </p>
            {user?.full_name && (
              <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                {user.email}
              </p>
            )}
          </div>
        </>
      )}
    </aside>
  )
}
