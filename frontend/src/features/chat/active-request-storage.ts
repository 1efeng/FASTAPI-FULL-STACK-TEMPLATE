const ACTIVE_REQUEST_KEY = "travel_agent_active_request"

export type ActiveRequest = {
  requestId: string
  conversationId: string
}

export function saveActiveRequest(
  requestId: string,
  conversationId: string,
): void {
  const activeRequest: ActiveRequest = { requestId, conversationId }
  localStorage.setItem(ACTIVE_REQUEST_KEY, JSON.stringify(activeRequest))
}

export function readActiveRequest(
  conversationId: string,
): ActiveRequest | null {
  const encoded = localStorage.getItem(ACTIVE_REQUEST_KEY)
  if (!encoded) return null
  try {
    const activeRequest = JSON.parse(encoded) as Partial<ActiveRequest>
    if (
      activeRequest.conversationId === conversationId &&
      typeof activeRequest.requestId === "string"
    ) {
      return { requestId: activeRequest.requestId, conversationId }
    }
    return null
  } catch {
    localStorage.removeItem(ACTIVE_REQUEST_KEY)
    return null
  }
}

export function clearActiveRequest(activeRequest: ActiveRequest): void {
  const current = readActiveRequest(activeRequest.conversationId)
  if (current?.requestId !== activeRequest.requestId) return
  localStorage.removeItem(ACTIVE_REQUEST_KEY)
}

export function clearActiveRequestForConversation(
  conversationId: string,
): void {
  const current = readActiveRequest(conversationId)
  if (current) localStorage.removeItem(ACTIVE_REQUEST_KEY)
}
