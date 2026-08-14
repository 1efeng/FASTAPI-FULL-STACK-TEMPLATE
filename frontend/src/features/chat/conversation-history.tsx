import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  MessageSquareText,
  MoreHorizontal,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

const TOKEN_KEY = "access_token"

export type ConversationSummary = {
  id: string
  title: string | null
  last_message_at: string | null
  created_at: string
  updated_at: string
}

type ConversationsResponse = {
  data: ConversationSummary[]
  count: number
}

type ConversationHistoryProps = {
  activeConversationId?: string
  disabled?: boolean
  onNewConversation: () => void
  onSelectConversation: (conversationId: string) => void
}

async function loadConversations(): Promise<ConversationsResponse> {
  const response = await fetch("/api/v1/conversations/?limit=100", {
    headers: {
      Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY) ?? ""}`,
    },
  })
  if (!response.ok) {
    throw new Error(`failed to load conversations: ${response.status}`)
  }
  return (await response.json()) as ConversationsResponse
}

async function renameConversation(
  conversationId: string,
  title: string,
): Promise<void> {
  const response = await fetch(`/api/v1/conversations/${conversationId}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY) ?? ""}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title }),
  })
  if (!response.ok) {
    throw new Error(`failed to rename conversation: ${response.status}`)
  }
}

async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(`/api/v1/conversations/${conversationId}`, {
    method: "DELETE",
    headers: {
      Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY) ?? ""}`,
    },
  })
  if (!response.ok) {
    throw new Error(`failed to delete conversation: ${response.status}`)
  }
}

const GROUP_ORDER = ["今天", "7 天内", "30 天内", "更早"] as const
type ConversationGroup = (typeof GROUP_ORDER)[number]

function conversationGroup(
  conversation: ConversationSummary,
): ConversationGroup {
  const value = conversation.last_message_at ?? conversation.created_at
  const date = new Date(value)
  const now = new Date()
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  )
  const startOfConversationDay = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  )
  const daysAgo = Math.floor(
    (startOfToday.getTime() - startOfConversationDay.getTime()) / 86_400_000,
  )

  if (daysAgo <= 0) return "今天"
  if (daysAgo < 7) return "7 天内"
  if (daysAgo < 30) return "30 天内"
  return "更早"
}

export function ConversationHistory({
  activeConversationId,
  disabled = false,
  onNewConversation,
  onSelectConversation,
}: ConversationHistoryProps) {
  const [editingConversation, setEditingConversation] =
    useState<ConversationSummary | null>(null)
  const [deletingConversation, setDeletingConversation] =
    useState<ConversationSummary | null>(null)
  const [draftTitle, setDraftTitle] = useState("")
  const queryClient = useQueryClient()
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: loadConversations,
    retry: 1,
  })
  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      renameConversation(id, title),
    onSuccess: async (_, { id }) => {
      setEditingConversation(null)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["conversations"] }),
        queryClient.invalidateQueries({ queryKey: ["conversation", id] }),
      ])
    },
  })
  const deleteMutation = useMutation({
    mutationFn: deleteConversation,
    onSuccess: async (_, deletedConversationId) => {
      setDeletingConversation(null)
      await queryClient.invalidateQueries({ queryKey: ["conversations"] })
      if (deletedConversationId === activeConversationId) {
        onNewConversation()
      }
    },
  })

  const filteredConversations = conversations.data?.data ?? []

  const groupedConversations = useMemo(() => {
    const groups = new Map<ConversationGroup, ConversationSummary[]>()
    for (const conversation of filteredConversations) {
      const group = conversationGroup(conversation)
      groups.set(group, [...(groups.get(group) ?? []), conversation])
    }
    return GROUP_ORDER.flatMap((group) => {
      const items = groups.get(group)
      return items ? [{ group, items }] : []
    })
  }, [filteredConversations])

  return (
    <div className="flex h-full min-h-0 flex-col bg-sidebar">
      <div className="px-3 pb-2 pt-3">
        <Button
          className="h-10 w-full justify-center gap-1.5 rounded-[16px] border bg-background font-normal text-foreground shadow-sm hover:bg-muted/60 hover:text-foreground"
          disabled={disabled}
          onClick={onNewConversation}
        >
          <Plus className="size-4" />
          新对话
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {conversations.isPending && (
          <div className="space-y-2 px-1">
            {[0, 1, 2, 3].map((item) => (
              <Skeleton key={item} className="h-9 rounded-lg" />
            ))}
          </div>
        )}

        {conversations.isError && (
          <div className="mx-1 rounded-xl border border-dashed p-4 text-center">
            <p className="text-sm text-muted-foreground">对话记录加载失败</p>
            <Button
              className="mt-2"
              onClick={() => void conversations.refetch()}
              size="sm"
              variant="ghost"
            >
              重新加载
            </Button>
          </div>
        )}

        {!conversations.isPending &&
          !conversations.isError &&
          filteredConversations.length === 0 && (
            <div className="flex flex-col items-center px-4 py-10 text-center">
              <MessageSquareText className="size-5 text-muted-foreground/60" />
              <p className="mt-2 text-sm text-muted-foreground">还没有对话</p>
              <p className="mt-0.5 text-xs text-muted-foreground/80">
                从一次新的旅行咨询开始
              </p>
            </div>
          )}

        {groupedConversations.map(({ group, items }) => (
          <section className="mt-4" key={group}>
            <h2 className="px-3 pb-1.5 text-xs font-normal text-muted-foreground/50">
              {group}
            </h2>
            <div className="space-y-0.5">
              {items.map((conversation) => {
                const isActive = conversation.id === activeConversationId
                return (
                  <div
                    aria-current={isActive ? "page" : undefined}
                    className={cn(
                      "group/conversation flex h-10 w-full items-center gap-1 rounded-lg px-2.5 text-left transition-colors",
                      isActive
                        ? "bg-[#4d6bfe]/10 text-[#4d6bfe]"
                        : "text-sidebar-foreground/80 hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground",
                    )}
                    key={conversation.id}
                  >
                    <button
                      className="min-w-0 flex-1 py-2 text-left"
                      disabled={disabled && !isActive}
                      onClick={() => onSelectConversation(conversation.id)}
                      type="button"
                    >
                      <p className="truncate text-sm">
                        {conversation.title ?? "新的对话"}
                      </p>
                    </button>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          aria-label={`管理对话：${conversation.title ?? "新的对话"}`}
                          className={cn(
                            "-mr-2 size-7 shrink-0 text-muted-foreground transition-opacity",
                            isActive
                              ? "opacity-100"
                              : "opacity-100 sm:opacity-0 sm:group-hover/conversation:opacity-100 sm:focus-visible:opacity-100",
                          )}
                          disabled={disabled}
                          size="icon-sm"
                          variant="ghost"
                        >
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" side="right">
                        <DropdownMenuItem
                          onSelect={() => {
                            renameMutation.reset()
                            setDraftTitle(conversation.title ?? "新的对话")
                            setEditingConversation(conversation)
                          }}
                        >
                          <Pencil />
                          重命名
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onSelect={() => {
                            deleteMutation.reset()
                            setDeletingConversation(conversation)
                          }}
                          variant="destructive"
                        >
                          <Trash2 />
                          删除
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                )
              })}
            </div>
          </section>
        ))}
      </div>

      <Dialog
        onOpenChange={(open) => !open && setEditingConversation(null)}
        open={Boolean(editingConversation)}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>重命名对话</DialogTitle>
            <DialogDescription>使用一个便于查找的对话名称。</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              const title = draftTitle.trim()
              if (!editingConversation || !title) return
              renameMutation.mutate({ id: editingConversation.id, title })
            }}
          >
            <Input
              aria-label="对话名称"
              autoFocus
              maxLength={255}
              onChange={(event) => setDraftTitle(event.target.value)}
              value={draftTitle}
            />
            {renameMutation.isError && (
              <p className="text-sm text-destructive">重命名失败，请重试。</p>
            )}
            <DialogFooter>
              <Button
                onClick={() => {
                  renameMutation.reset()
                  setEditingConversation(null)
                }}
                type="button"
                variant="outline"
              >
                取消
              </Button>
              <Button
                disabled={!draftTitle.trim() || renameMutation.isPending}
                type="submit"
              >
                保存
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        onOpenChange={(open) => !open && setDeletingConversation(null)}
        open={Boolean(deletingConversation)}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>删除这个对话？</DialogTitle>
            <DialogDescription>
              “{deletingConversation?.title ?? "新的对话"}
              ”及其消息记录将永久删除，此操作无法撤销。
            </DialogDescription>
          </DialogHeader>
          {deleteMutation.isError && (
            <p className="text-sm text-destructive">删除失败，请重试。</p>
          )}
          <DialogFooter>
            <Button
              onClick={() => {
                deleteMutation.reset()
                setDeletingConversation(null)
              }}
              variant="outline"
            >
              取消
            </Button>
            <Button
              disabled={deleteMutation.isPending}
              onClick={() => {
                if (deletingConversation) {
                  deleteMutation.mutate(deletingConversation.id)
                }
              }}
              variant="destructive"
            >
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
