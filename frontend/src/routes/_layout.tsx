import {
  createFileRoute,
  Outlet,
  redirect,
  useRouterState,
} from "@tanstack/react-router"

import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { ChatNavigationProvider } from "@/features/chat/chat-navigation-context"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

function Layout() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const isChat = pathname === "/chat"

  return (
    <ChatNavigationProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset className={isChat ? "h-svh min-h-0 overflow-hidden" : ""}>
          {!isChat && (
            <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b bg-background/90 px-4 backdrop-blur">
              <SidebarTrigger className="-ml-1 text-muted-foreground" />
            </header>
          )}
          <main
            className={
              isChat ? "min-h-0 flex-1 overflow-hidden" : "flex-1 p-6 md:p-8"
            }
          >
            {isChat ? (
              <Outlet />
            ) : (
              <div className="mx-auto max-w-7xl">
                <Outlet />
              </div>
            )}
          </main>
          {!isChat && <Footer />}
        </SidebarInset>
      </SidebarProvider>
    </ChatNavigationProvider>
  )
}
