import { expect, test } from "@playwright/test"

// Opt-in E2E: requires live Aegra (aegra serve) + real LLM + FastAPI login.
// Run with: AEGRA_E2E=1 bunx playwright test chat-recovery.verify
const RUN = process.env.AEGRA_E2E === "1"
test.skip(!RUN, "AEGRA_E2E=1 not set")

const PROMPT = "用一句话介绍你自己，不要用工具"

test("chat: send, stream, reload, recover same thread", async ({ page }) => {
  await page.goto("/")

  // initial empty state
  await expect(page.getByText("有什么可以帮你？")).toBeVisible({ timeout: 15000 })

  const composer = page.getByRole("textbox", { name: "消息" })
  await composer.fill(PROMPT)
  await page.getByRole("button", { name: "发送消息" }).click()

  // wait until two messages (human + ai) are rendered: generation finished
  await expect(page.locator("article")).toHaveCount(2, { timeout: 120000 })
  await expect(page.locator("article").nth(1)).not.toBeEmpty()

  // reload page: same thread must recover human + assistant messages
  await page.reload()
  await expect(page.getByText(PROMPT)).toBeVisible({ timeout: 30000 })
  await expect(page.locator("article")).toHaveCount(2, { timeout: 30000 })
  await expect(page.locator("article").nth(1)).not.toBeEmpty()
})
