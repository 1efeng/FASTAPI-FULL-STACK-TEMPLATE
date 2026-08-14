import { Link } from "@tanstack/react-router"
import { Compass } from "lucide-react"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "mark" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content =
    variant === "responsive" ? (
      <>
        <span
          className={cn(
            "flex items-center gap-2.5 group-data-[collapsible=icon]:hidden",
            className,
          )}
        >
          <span className="flex size-8 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <Compass className="size-4.5" />
          </span>
          <span className="flex flex-col leading-none">
            <span className="text-base font-semibold tracking-tight">行伴</span>
            <span className="mt-1 text-[10px] text-muted-foreground">
              AI TRAVEL COMPANION
            </span>
          </span>
        </span>
        <span
          className={cn(
            "hidden size-8 items-center justify-center rounded-xl bg-primary text-primary-foreground group-data-[collapsible=icon]:flex",
            className,
          )}
        >
          <Compass className="size-4.5" />
        </span>
      </>
    ) : (
      <span
        className={cn(
          "flex items-center gap-2.5",
          variant === "icon" &&
            "size-8 justify-center rounded-xl bg-primary text-primary-foreground",
          variant === "mark" &&
            "size-11 justify-center rounded-full bg-[#4d6bfe] text-white shadow-sm",
          className,
        )}
      >
        <Compass className={cn("size-4.5", variant === "mark" && "size-5")} />
        {variant === "full" && (
          <span className="font-semibold text-[#4d6bfe] text-[20px] tracking-[-0.03em]">
            行伴
          </span>
        )}
      </span>
    )

  if (!asLink) {
    return content
  }

  return <Link to="/chat">{content}</Link>
}
