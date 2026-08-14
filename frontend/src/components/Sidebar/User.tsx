import { Link as RouterLink } from "@tanstack/react-router"
import { LogOut, Monitor, Moon, MoreHorizontal, Palette, Settings, ShieldCheck, Sun } from "lucide-react"

import { type Theme, useTheme } from "@/components/theme-provider"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { getInitials } from "@/utils"

interface UserInfoProps {
  fullName?: string
  email?: string
  showEmail?: boolean
}

function UserInfo({ fullName, email, showEmail = true }: UserInfoProps) {
  return (
    <div className="flex items-center gap-2.5 w-full min-w-0">
      <Avatar className="size-9">
        <AvatarFallback className="bg-[#dfe4ff] font-medium text-[#4d6bfe]">
          {getInitials(fullName || "User")}
        </AvatarFallback>
      </Avatar>
      <div className="flex flex-col items-start min-w-0">
        <p className="w-full truncate text-sm font-medium">{fullName || email || "用户"}</p>
        {showEmail && email && (
          <p className="text-xs text-muted-foreground truncate w-full">
            {email}
          </p>
        )}
      </div>
    </div>
  )
}

export function User({ user }: { user: any }) {
  const { logout } = useAuth()
  const { setTheme, theme } = useTheme()
  const { isMobile, setOpenMobile } = useSidebar()

  if (!user) return null

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }
  const handleLogout = async () => {
    logout()
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="h-12 rounded-xl px-2 hover:bg-[#e7e8eb] data-[state=open]:bg-[#e7e8eb] data-[state=open]:text-sidebar-accent-foreground"
              data-testid="user-menu"
            >
              <UserInfo fullName={user?.full_name} email={user?.email} showEmail={false} />
              <MoreHorizontal className="ml-auto size-4 text-muted-foreground" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
            side={isMobile ? "bottom" : "right"}
            align="end"
            sideOffset={4}
          >
            <DropdownMenuLabel className="truncate px-2 py-1.5 text-xs font-normal text-muted-foreground">
              {user?.email}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            {user.is_superuser && (
              <RouterLink to="/admin" onClick={handleMenuClick}>
                <DropdownMenuItem>
                  <ShieldCheck />
                  管理后台
                </DropdownMenuItem>
              </RouterLink>
            )}
            <RouterLink to="/settings" onClick={handleMenuClick}>
              <DropdownMenuItem>
                <Settings />
                用户设置
              </DropdownMenuItem>
            </RouterLink>
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <Palette />
                主题设置
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent className="min-w-40">
                <DropdownMenuRadioGroup
                  onValueChange={(value) => setTheme(value as Theme)}
                  value={theme}
                >
                  <DropdownMenuRadioItem value="light">
                    <Sun />
                    浅色
                  </DropdownMenuRadioItem>
                  <DropdownMenuRadioItem value="dark">
                    <Moon />
                    深色
                  </DropdownMenuRadioItem>
                  <DropdownMenuRadioItem value="system">
                    <Monitor />
                    跟随系统
                  </DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
              </DropdownMenuSubContent>
            </DropdownMenuSub>
            <DropdownMenuItem onClick={handleLogout}>
              <LogOut />
              退出登录
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}





