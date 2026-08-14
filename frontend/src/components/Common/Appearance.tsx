import { Monitor, Moon, Sun } from "lucide-react"

import { type Theme, useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

type LucideIcon = React.FC<React.SVGProps<SVGSVGElement>>

const ICON_MAP: Record<Theme, LucideIcon> = {
  system: Monitor,
  light: Sun,
  dark: Moon,
}

export const SidebarAppearance = () => {
  const { isMobile } = useSidebar()
  const { setTheme, theme } = useTheme()
  const Icon = ICON_MAP[theme]

  return (
    <SidebarMenuItem>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <SidebarMenuButton tooltip="外观" data-testid="theme-button">
            <Icon className="size-4 text-muted-foreground" />
            <span>外观</span>
            <span className="sr-only">Toggle theme</span>
          </SidebarMenuButton>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side={isMobile ? "top" : "right"}
          align="end"
          className="w-(--radix-dropdown-menu-trigger-width) min-w-56"
        >
          <DropdownMenuItem
            data-testid="light-mode"
            onClick={() => setTheme("light")}
          >
            <Sun className="mr-2 h-4 w-4" />
            浅色
          </DropdownMenuItem>
          <DropdownMenuItem
            data-testid="dark-mode"
            onClick={() => setTheme("dark")}
          >
            <Moon className="mr-2 h-4 w-4" />
            深色
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setTheme("system")}>
            <Monitor className="mr-2 h-4 w-4" />
            跟随系统
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </SidebarMenuItem>
  )
}

export const Appearance = () => {
  const { setTheme } = useTheme()

  return (
    <div className="flex items-center justify-center">
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button data-testid="theme-button" variant="outline" size="icon">
            <Sun className="h-[1.2rem] w-[1.2rem] rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
            <Moon className="absolute h-[1.2rem] w-[1.2rem] rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
            <span className="sr-only">Toggle theme</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            data-testid="light-mode"
            onClick={() => setTheme("light")}
          >
            <Sun className="mr-2 h-4 w-4" />
            Light
          </DropdownMenuItem>
          <DropdownMenuItem
            data-testid="dark-mode"
            onClick={() => setTheme("dark")}
          >
            <Moon className="mr-2 h-4 w-4" />
            Dark
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setTheme("system")}>
            <Monitor className="mr-2 h-4 w-4" />
            System
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
const THEME_OPTIONS: Array<{
  value: Theme
  label: string
  description: string
  icon: LucideIcon
}> = [
  { value: "light", label: "浅色", description: "始终使用浅色外观", icon: Sun },
  { value: "dark", label: "深色", description: "始终使用深色外观", icon: Moon },
  { value: "system", label: "跟随系统", description: "自动匹配系统设置", icon: Monitor },
]

export const AppearanceSettings = () => {
  const { setTheme, theme } = useTheme()

  return (
    <div className="max-w-2xl rounded-xl border bg-card p-5">
      <div>
        <h2 className="text-base font-semibold">外观</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          选择行伴在当前设备上的显示方式。
        </p>
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        {THEME_OPTIONS.map(({ value, label, description, icon: Icon }) => {
          const selected = theme === value
          return (
            <button
              aria-pressed={selected}
              className={selected ? "rounded-xl border border-[#4d6bfe] bg-[#4d6bfe]/5 p-4 text-left ring-1 ring-[#4d6bfe]/20" : "rounded-xl border bg-background p-4 text-left transition-colors hover:bg-muted/60"}
              key={value}
              onClick={() => setTheme(value)}
              type="button"
            >
              <Icon className={selected ? "size-5 text-[#4d6bfe]" : "size-5 text-muted-foreground"} />
              <p className="mt-3 text-sm font-medium">{label}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p>
            </button>
          )
        })}
      </div>
    </div>
  )
}

