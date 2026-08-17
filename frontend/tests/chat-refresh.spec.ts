import { expect, test } from "@playwright/test"

const conversationId = "11111111-1111-4111-8111-111111111111"
const requestId = "55555555-5555-4555-8555-555555555555"
const secondConversationId = "66666666-6666-4666-8666-666666666666"

const conversation = {
  id: conversationId,
  title: "Tokyo plan",
  last_message_at: "2026-08-13T08:00:00Z",
  created_at: "2026-08-13T07:00:00Z",
  updated_at: "2026-08-13T08:00:00Z",
  messages: [
    {
      id: "22222222-2222-4222-8222-222222222222",
      role: "user",
      content: "帮我规划东京三日游",
      reasoning_summary: null,
      created_at: "2026-08-13T07:59:00Z",
    },
    {
      id: "33333333-3333-4333-8333-333333333333",
      role: "assistant",
      content: "第一天先从浅草和晴空塔开始。",
      reasoning_summary: "先按区域聚合景点，再减少跨城移动。",
      created_at: "2026-08-13T08:00:00Z",
    },
  ],
}

test.describe("Chat conversation refresh", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(
      () => {
        localStorage.setItem("access_token", "test-token")
      },
      { currentConversationId: conversationId },
    )
    await page.route("**/api/v1/users/me", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "44444444-4444-4444-8444-444444444444",
          email: "chat@example.com",
          is_active: true,
          is_superuser: false,
          full_name: "Chat User",
        }),
      })
    })
  })

  test("restores the current conversation from the URL after reload", async ({
    page,
  }) => {
    await page.route(
      `**/api/v1/conversations/${conversationId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(conversation),
        })
      },
    )

    await page.goto(`/chat?conversation=${conversationId}`)

    await expect(page).toHaveURL(
      new RegExp(`/chat\\?conversation=${conversationId}$`),
    )
    await expect(page.getByText("帮我规划东京三日游")).toBeVisible()
    await expect(page.getByText("第一天先从浅草和晴空塔开始。")).toBeVisible()
    await page.getByText("已思考").click()
    await expect(page.getByText("已思考")).toBeVisible()
    await expect(
      page.getByText("先按区域聚合景点，再减少跨城移动。"),
    ).toBeVisible()

    await page.reload()

    await expect(page.getByText("帮我规划东京三日游")).toBeVisible()
    await expect(page.getByText("第一天先从浅草和晴空塔开始。")).toBeVisible()
    await page.getByText("已思考").click()
    await expect(page.getByText("已思考")).toBeVisible()
    await expect(
      page.getByText("先按区域聚合景点，再减少跨城移动。"),
    ).toBeVisible()
  })

  test("switches conversation history and starts a clean new chat", async ({
    page,
  }) => {
    const secondConversation = {
      ...conversation,
      id: secondConversationId,
      title: "大阪美食周末",
      messages: [
        {
          ...conversation.messages[0],
          id: "77777777-7777-4777-8777-777777777777",
          content: "大阪周末吃什么？",
        },
      ],
    }
    await page.route(
      /\/api\/v1\/conversations\/\?limit=100$/,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: [
              {
                id: conversation.id,
                title: conversation.title,
                last_message_at: conversation.last_message_at,
                created_at: conversation.created_at,
                updated_at: conversation.updated_at,
              },
              {
                id: secondConversation.id,
                title: secondConversation.title,
                last_message_at: secondConversation.last_message_at,
                created_at: secondConversation.created_at,
                updated_at: secondConversation.updated_at,
              },
            ],
            count: 2,
          }),
        })
      },
    )
    await page.route(
      `**/api/v1/conversations/${conversationId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(conversation),
        })
      },
    )
    await page.route(
      `**/api/v1/conversations/${secondConversationId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(secondConversation),
        })
      },
    )

    await page.goto(`/chat?conversation=${conversationId}`)

    await expect(
      page.getByRole("button", { name: "Tokyo plan", exact: true }),
    ).toBeVisible()
    await page.getByText("大阪美食周末").click()
    await expect(page).toHaveURL(
      new RegExp(`/chat\\?conversation=${secondConversationId}$`),
    )
    await expect(page.getByText("大阪周末吃什么？")).toBeVisible()

    await page.evaluate(
      ({ activeConversationId }) => {
        localStorage.setItem(
          "travel_agent_active_request",
          JSON.stringify({
            conversationId: activeConversationId,
            requestId: "old-active-request",
          }),
        )
      },
      { activeConversationId: secondConversationId },
    )

    await page.getByRole("button", { name: "新对话" }).click()
    await expect(page).toHaveURL(/\/chat$/)
    await expect(page.getByText("有什么旅行问题我能帮你的吗？")).toBeVisible()
    await expect
      .poll(() =>
        page.evaluate(() =>
          localStorage.getItem("travel_agent_active_request"),
        ),
      )
      .toBeNull()
  })

  test("treats bare chat as a draft and creates its conversation in the stream turn", async ({
    page,
  }) => {
    let conversationPostCalls = 0
    let requestBody: Record<string, unknown> | undefined
    await page.route("**/api/v1/conversations/?limit=100", async (route) => {
      if (route.request().method() === "POST") conversationPostCalls += 1
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: [], count: 0 }),
      })
    })
    await page.route(
      `**/api/v1/conversations/${conversationId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...conversation, messages: [] }),
        })
      },
    )
    await page.route("**/api/v1/chat/stream", async (route) => {
      requestBody = route.request().postDataJSON() as Record<string, unknown>
      await route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "X-Request-Id": requestId,
          "X-Conversation-Id": conversationId,
          "x-vercel-ai-ui-message-stream": "v1",
        },
        body: [
          { type: "start", messageId: requestId },
          { type: "text-start", id: "answer" },
          { type: "text-delta", id: "answer", delta: "首条回复" },
          { type: "text-end", id: "answer" },
          { type: "finish" },
          "[DONE]",
        ]
          .map(
            (chunk) =>
              `data: ${typeof chunk === "string" ? chunk : JSON.stringify(chunk)}\n\n`,
          )
          .join(""),
      })
    })

    await page.goto("/chat")
    await expect(page).toHaveURL(/\/chat$/)
    await expect(page.getByText("有什么旅行问题我能帮你的吗？")).toBeVisible()

    await page.getByPlaceholder("给行伴发送消息").fill("规划一次东京旅行")
    await page.getByRole("button", { name: "Submit" }).click()

    await expect(page).toHaveURL(
      new RegExp(`/chat\\?conversation=${conversationId}$`),
    )
    await expect(page.getByText("首条回复")).toBeVisible()
    await expect.poll(() => conversationPostCalls).toBe(0)
    await expect.poll(() => requestBody?.conversation_id).toBeNull()
  })

  test("shows a visible error when the stream returns a product error", async ({
    page,
  }) => {
    await page.route(
      `**/api/v1/conversations/${conversationId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...conversation, messages: [] }),
        })
      },
    )
    await page.route("**/api/v1/chat/stream", async (route) => {
      await route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "X-Request-Id": requestId,
          "X-Conversation-Id": conversationId,
          "x-vercel-ai-ui-message-stream": "v1",
        },
        body: [
          { type: "start", messageId: requestId },
          { type: "error", errorText: "当前规划服务暂时不可用，请稍后重试。" },
          "[DONE]",
        ]
          .map(
            (chunk) =>
              `data: ${typeof chunk === "string" ? chunk : JSON.stringify(chunk)}\n\n`,
          )
          .join(""),
      })
    })

    await page.goto(`/chat?conversation=${conversationId}`)
    await page.getByPlaceholder("给行伴发送消息").fill("查一下东京的天气")
    await page.getByRole("button", { name: "Submit" }).click()

    await expect(page.getByRole("alert")).toContainText(
      "当前规划服务暂时不可用，请稍后重试。",
    )
  })

  test("reattaches and replays an active assistant stream after reload", async ({
    page,
  }) => {
    await page.addInitScript(
      ({ currentConversationId, activeRequestId }) => {
        localStorage.setItem(
          "travel_agent_active_request",
          JSON.stringify({
            conversationId: currentConversationId,
            requestId: activeRequestId,
          }),
        )
      },
      {
        currentConversationId: conversationId,
        activeRequestId: requestId,
      },
    )
    await page.route(
      `**/api/v1/conversations/${conversationId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...conversation,
            messages: [conversation.messages[0]],
          }),
        })
      },
    )
    let requestStatusCalls = 0
    await page.route(`**/api/v1/chat/requests/${requestId}`, async (route) => {
      requestStatusCalls += 1
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          request_id: requestId,
          conversation_id: conversationId,
          status: "running",
          error_code: null,
          started_at: "2026-08-13T07:59:00Z",
          deadline_at: "2026-08-13T08:01:00Z",
          finished_at: null,
        }),
      })
    })
    await page.route(
      `**/api/v1/chat/requests/${requestId}/stream`,
      async (route) => {
        const chunks = [
          { type: "start", messageId: "streamed-assistant" },
          { type: "text-start", id: "answer" },
          {
            type: "text-delta",
            id: "answer",
            delta: "这是刷新后从活动流重放的回答。",
          },
          { type: "text-end", id: "answer" },
          { type: "finish" },
        ]
          .map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`)
          .join("")

        await route.fulfill({
          status: 200,
          headers: {
            "Content-Type": "text/event-stream",
            "x-vercel-ai-ui-message-stream": "v1",
          },
          body: `${chunks}data: [DONE]\n\n`,
        })
      },
    )

    await page.goto(`/chat?conversation=${conversationId}`)

    await expect(page.getByText("这是刷新后从活动流重放的回答。")).toBeVisible()
    await expect.poll(() => requestStatusCalls).toBe(0)
    await expect
      .poll(() =>
        page.evaluate(() =>
          localStorage.getItem("travel_agent_active_request"),
        ),
      )
      .toBeNull()
  })

  test("reconciles durable history when reconnect returns 204", async ({
    page,
  }) => {
    await page.addInitScript(
      ({ currentConversationId, activeRequestId }) => {
        localStorage.setItem(
          "travel_agent_active_request",
          JSON.stringify({
            conversationId: currentConversationId,
            requestId: activeRequestId,
          }),
        )
      },
      {
        currentConversationId: conversationId,
        activeRequestId: requestId,
      },
    )

    let conversationCalls = 0
    await page.route(
      `**/api/v1/conversations/${conversationId}`,
      async (route) => {
        conversationCalls += 1
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...conversation,
            messages:
              conversationCalls === 1
                ? [conversation.messages[0]]
                : conversation.messages,
          }),
        })
      },
    )

    let requestStatusCalls = 0
    await page.route(`**/api/v1/chat/requests/${requestId}`, async (route) => {
      requestStatusCalls += 1
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          request_id: requestId,
          conversation_id: conversationId,
          status: "completed",
        }),
      })
    })
    await page.route(
      `**/api/v1/chat/requests/${requestId}/stream`,
      async (route) => {
        await route.fulfill({ status: 204 })
      },
    )

    await page.goto(`/chat?conversation=${conversationId}`)

    await expect(page.getByText("第一天先从浅草和晴空塔开始。")).toBeVisible()
    await expect.poll(() => requestStatusCalls).toBe(0)
    await expect.poll(() => conversationCalls).toBe(2)
    await expect
      .poll(() =>
        page.evaluate(() =>
          localStorage.getItem("travel_agent_active_request"),
        ),
      )
      .toBeNull()
  })

  test("uses Product cancel before detaching an active stream", async ({
    page,
  }) => {
    await page.route(
      `**/api/v1/conversations/${conversationId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...conversation, messages: [] }),
        })
      },
    )
    let releaseInitialPost: () => void = () => undefined
    const initialPostReleased = new Promise<void>((resolve) => {
      releaseInitialPost = resolve
    })
    await page.route("**/api/v1/chat/stream", async (route) => {
      await initialPostReleased
      try {
        await route.fulfill({
          status: 204,
        })
      } catch {
        // Product cancellation aborts the pending AI SDK subscriber.
      }
    })
    let cancelCalls = 0
    await page.route(
      `**/api/v1/chat/requests/${requestId}/cancel`,
      async (route) => {
        cancelCalls += 1
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            request_id: requestId,
            conversation_id: conversationId,
            status: "cancelled",
          }),
        })
        setTimeout(releaseInitialPost, 250)
      },
    )

    await page.goto(`/chat?conversation=${conversationId}`)
    await page.getByPlaceholder("给行伴发送消息").fill("请生成一个行程")
    await page.getByRole("button", { name: "Submit" }).click()
    await expect(page.getByRole("button", { name: "Stop" })).toBeVisible()
    await page.evaluate(
      ({ currentConversationId, activeRequestId }) => {
        localStorage.setItem(
          "travel_agent_active_request",
          JSON.stringify({
            conversationId: currentConversationId,
            requestId: activeRequestId,
          }),
        )
      },
      {
        currentConversationId: conversationId,
        activeRequestId: requestId,
      },
    )
    await page.getByRole("button", { name: "Stop" }).click()
    await expect.poll(() => cancelCalls).toBe(1)
    await expect
      .poll(() =>
        page.evaluate(() =>
          localStorage.getItem("travel_agent_active_request"),
        ),
      )
      .toBeNull()
  })
})
