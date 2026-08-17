const CHAT_STORAGE_KEYS = ["travel_agent_active_request"] as const

export function getAccessToken(): string {
  return localStorage.getItem("access_token") ?? ""
}

export function getAuthHeaders(): Record<string, string> {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function redirectToLogin(): void {
  localStorage.removeItem("access_token")
  for (const key of CHAT_STORAGE_KEYS) localStorage.removeItem(key)
  if (window.location.pathname !== "/login") {
    window.location.assign("/login")
  }
}

export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const requestInput =
    typeof input === "string" && input.startsWith("/")
      ? `${import.meta.env.VITE_API_URL ?? ""}${input}`
      : input
  const headers = new Headers(init?.headers)
  const authHeaders = getAuthHeaders()
  if (authHeaders.Authorization && !headers.has("Authorization")) {
    headers.set("Authorization", authHeaders.Authorization)
  }
  const response = await fetch(requestInput, { ...init, headers })
  if (response.status === 401 || response.status === 403) {
    redirectToLogin()
  }
  return response
}
