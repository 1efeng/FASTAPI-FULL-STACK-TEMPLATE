import { useNavigate } from "@tanstack/react-router"
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react"

const ACTIVE_REQUEST_KEY = "travel_agent_active_request"

type ChatNavigationContextValue = {
  isNavigationLocked: boolean
  setNavigationLocked: (locked: boolean) => void
  startNewConversation: () => void
}

const ChatNavigationContext = createContext<ChatNavigationContextValue | null>(
  null,
)

export function ChatNavigationProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const [isNavigationLocked, setNavigationLocked] = useState(false)

  const startNewConversation = useCallback(() => {
    localStorage.removeItem(ACTIVE_REQUEST_KEY)
    void navigate({ to: "/chat", search: {}, replace: true })
  }, [navigate])

  const value = useMemo(
    () => ({ isNavigationLocked, setNavigationLocked, startNewConversation }),
    [isNavigationLocked, startNewConversation],
  )

  return (
    <ChatNavigationContext.Provider value={value}>
      {children}
    </ChatNavigationContext.Provider>
  )
}

export function useChatNavigation() {
  const context = useContext(ChatNavigationContext)
  if (!context) {
    throw new Error(
      "useChatNavigation must be used within ChatNavigationProvider",
    )
  }
  return context
}
