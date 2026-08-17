"use client"

import { cjk } from "@streamdown/cjk"
import { AtomIcon, ChevronDownIcon } from "lucide-react"
import type { ComponentProps, ReactNode } from "react"
import {
  createContext,
  memo,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import { Streamdown } from "streamdown"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"

interface ReasoningContextValue {
  isReasoningStreaming: boolean
  isOpen: boolean
  setIsOpen: (open: boolean) => void
}

const ReasoningContext = createContext<ReasoningContextValue | null>(null)

const useReasoning = () => {
  const context = useContext(ReasoningContext)
  if (!context) {
    throw new Error("Reasoning components must be used within Reasoning")
  }
  return context
}

export type ReasoningProps = ComponentProps<typeof Collapsible> & {
  isStreaming?: boolean
  isReasoningStreaming?: boolean
}

const AUTO_CLOSE_DELAY = 1000

export const Reasoning = memo(
  ({
    className,
    isStreaming = false,
    isReasoningStreaming = isStreaming,
    children,
    ...props
  }: ReasoningProps) => {
    const [isOpen, setIsOpen] = useState(isStreaming)
    const hasEverStreamedRef = useRef(isStreaming)
    const [hasAutoClosed, setHasAutoClosed] = useState(false)

    useEffect(() => {
      if (isStreaming) {
        hasEverStreamedRef.current = true
      }
    }, [isStreaming])

    // Auto-open when streaming starts.
    useEffect(() => {
      if (isStreaming && !isOpen) {
        setIsOpen(true)
      }
    }, [isStreaming, isOpen])

    // Auto-close when streaming ends (once only, and only if it ever streamed).
    useEffect(() => {
      if (
        hasEverStreamedRef.current &&
        !isStreaming &&
        isOpen &&
        !hasAutoClosed
      ) {
        const timer = setTimeout(() => {
          setIsOpen(false)
          setHasAutoClosed(true)
        }, AUTO_CLOSE_DELAY)

        return () => clearTimeout(timer)
      }
    }, [isStreaming, isOpen, hasAutoClosed])

    const handleOpenChange = useCallback((newOpen: boolean) => {
      setIsOpen(newOpen)
    }, [])

    const contextValue = useMemo(
      () => ({ isOpen, isReasoningStreaming, setIsOpen }),
      [isOpen, isReasoningStreaming],
    )

    return (
      <ReasoningContext.Provider value={contextValue}>
        <Collapsible
          className={cn("not-prose mb-4", className)}
          onOpenChange={handleOpenChange}
          open={isOpen}
          {...props}
        >
          {children}
        </Collapsible>
      </ReasoningContext.Provider>
    )
  },
)

export type ReasoningTriggerProps = ComponentProps<
  typeof CollapsibleTrigger
> & {
  getThinkingMessage: (isStreaming: boolean) => ReactNode
}

export const ReasoningTrigger = memo(
  ({
    className,
    children,
    getThinkingMessage,
    ...props
  }: ReasoningTriggerProps) => {
    const { isOpen, isReasoningStreaming } = useReasoning()

    return (
      <CollapsibleTrigger
        className={cn(
          "flex w-full items-center gap-2 text-muted-foreground text-sm transition-colors hover:text-foreground",
          className,
        )}
        {...props}
      >
        {children ?? (
          <>
            <AtomIcon className="size-3.5 text-primary" strokeWidth={1.8} />
            {getThinkingMessage(isReasoningStreaming)}
            <ChevronDownIcon
              className={cn(
                "size-4 transition-transform",
                isOpen ? "rotate-180" : "rotate-0",
              )}
            />
          </>
        )}
      </CollapsibleTrigger>
    )
  },
)

export type ReasoningContentProps = ComponentProps<
  typeof CollapsibleContent
> & {
  children: string
}

const streamdownPlugins = { cjk }

export const ReasoningContent = memo(
  ({ className, children, ...props }: ReasoningContentProps) => (
    <CollapsibleContent
      className={cn(
        "mt-4 text-sm",
        "data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-top-2 data-[state=open]:slide-in-from-top-2 text-muted-foreground outline-none data-[state=closed]:animate-out data-[state=open]:animate-in",
        className,
      )}
      {...props}
    >
      <Streamdown plugins={streamdownPlugins}>{children}</Streamdown>
    </CollapsibleContent>
  ),
)

Reasoning.displayName = "Reasoning"
ReasoningTrigger.displayName = "ReasoningTrigger"
ReasoningContent.displayName = "ReasoningContent"
