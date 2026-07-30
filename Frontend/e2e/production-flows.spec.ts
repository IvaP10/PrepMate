import fs from "node:fs/promises"
import path from "node:path"
import { expect, test, type Page } from "@playwright/test"

const visualDirectory = path.join(process.cwd(), "e2e", ".generated", "release-visuals")

async function captureReleaseVisual(page: Page, name: string) {
  if (process.env.E2E_CAPTURE_VISUALS !== "true") return
  await fs.mkdir(visualDirectory, { recursive: true })
  await page.screenshot({ path: path.join(visualDirectory, `${name}.png`), fullPage: true })
}

test.describe("authenticated production lifecycle", () => {
  test.skip(process.env.E2E_REQUIRE_AUTH !== "true", "Requires a seeded disposable release account")

  test("Improve exposes one current action while future nodes stay locked", async ({ page }) => {
    const params = new URLSearchParams({
      tab: "improve",
      mission_id: process.env.E2E_MISSION_ID!,
      roadmap_node_id: process.env.E2E_ROADMAP_NODE_ID!,
      exercise_id: process.env.E2E_EXERCISE_ID!,
    })
    await page.goto(`/?${params}`)
    await expect(page.getByText("Interview learning path", { exact: true })).toBeVisible()
    await expect(page.getByText("Path progress", { exact: true })).toBeVisible()
    await expect(page.locator("ol button:enabled")).toHaveCount(1)
    await expect(page.getByRole("dialog")).toBeVisible()
    await expect(page.getByRole("button", { name: "Start", exact: true })).toBeVisible()
    await captureReleaseVisual(page, "authenticated-improve")
  })

  test("Improve persists and grades real candidate work", async ({ page }) => {
    test.skip(process.env.E2E_MUTATE_FIXTURES !== "true", "Requires a disposable mutation fixture")
    const params = new URLSearchParams({
      tab: "improve",
      mission_id: process.env.E2E_MISSION_ID!,
      roadmap_node_id: process.env.E2E_ROADMAP_NODE_ID!,
      exercise_id: process.env.E2E_EXERCISE_ID!,
    })
    await page.goto(`/?${params}`)
    await page.getByRole("button", { name: "Start", exact: true }).click()
    await expect(page.getByText("Attempt in progress")).toHaveCount(0)
    await page.getByLabel("Rewrite with exact ownership").fill(
      "I owned the idempotent job redesign, chose a database-backed lease after rejecting an in-memory lock, and reduced duplicate processing to zero while cutting p95 latency by 38 percent.",
    )
    await expect(page.getByRole("button", { name: "Submit attempt" })).toBeEnabled()
    await page.getByRole("button", { name: "Submit attempt" }).click()
    await expect(page.getByText("Done correctly")).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole("button", { name: /Continue to variation|Continue to recovery/ })).toBeVisible()
    await captureReleaseVisual(page, "improve-graded-attempt")
  })

  test("interview reconnect surface never exposes coaching or scores", async ({ page }) => {
    await page.goto(`/interview/${process.env.E2E_INTERVIEW_ID}`)
    await expect(page.getByRole("heading", { name: "Share your screen" })).toBeVisible()
    await expect(page.getByRole("button", { name: "Share screen" })).toBeVisible()
    await expect(page.getByText(/your score|coaching feedback/i)).toHaveCount(0)
    await captureReleaseVisual(page, "interview-preflight")
    await page.reload()
    await expect(page).toHaveURL(new RegExp(`/interview/${process.env.E2E_INTERVIEW_ID}`))
  })

  test("technical round and report polling render", async ({ page }) => {
    await page.goto(`/interview/${process.env.E2E_TECHNICAL_ID}/technical`)
    await expect(page.getByText(/technical/i).first()).toBeVisible()
    await expect(page.getByRole("button", { name: /run|submit/i }).first()).toBeVisible()
    await expect(page.getByText(/first non-repeating character/i)).toBeVisible()
    await expect(page.getByText("Loading...", { exact: true })).toHaveCount(0, { timeout: 15_000 })
    await expect(page.locator(".monaco-editor")).toBeVisible()
    await captureReleaseVisual(page, "technical-round")
    await page.goto(`/interview/${process.env.E2E_REPORT_ID}/report`)
    await expect(page.getByRole("heading", { name: "Interview Round Report" })).toBeVisible()
    await expect(page.getByText(/communicated the architecture clearly/i)).toBeVisible()
    await expect(page.getByText("Evidence-backed findings")).toBeVisible()
    await captureReleaseVisual(page, "interview-report")
  })

  test("permission denial remains a truthful blocking state", async ({ browser, baseURL }) => {
    const context = await browser.newContext({
      baseURL,
      storageState: path.join(process.cwd(), "e2e", ".generated", "auth.json"),
    })
    await context.clearPermissions()
    const page = await context.newPage()
    await page.goto(`/interview/${process.env.E2E_INTERVIEW_ID}`)
    await expect(page.getByText(/permission|microphone|camera|screen share|required/i).first()).toBeVisible()
    await captureReleaseVisual(page, "permission-blocked")
    await context.close()
  })

  test("controlled camera, microphone, and screen media enter the live interview workspace", async ({ page }) => {
    test.skip(process.env.E2E_MUTATE_FIXTURES !== "true", "Requires a disposable mutation fixture")
    test.setTimeout(90_000)
    await page.goto("/?tab=interview")
    await expect(page.getByRole("radiogroup", { name: "Interview profile" })).toBeVisible()
    await page.getByRole("button", { name: "Start Interview Round", exact: true }).click()
    await expect(page).toHaveURL(/\/interview\/[a-f0-9-]+(?:\?.*)?$/, { timeout: 30_000 })
    await expect(page.getByRole("button", { name: /End Interview|Leave interview/ })).toBeVisible({ timeout: 20_000 })
    await expect(page.getByRole("heading", { name: /Hi .* I am /i })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText("Warm-up", { exact: true })).toBeVisible()
    await expect(page.getByText(/Starting interview/i)).toBeHidden({ timeout: 20_000 })
    await expect(page.getByText(/Camera/).first()).toBeVisible()
    await expect(page.getByText(/your score|coaching feedback/i)).toHaveCount(0)
    await page.waitForTimeout(500)
    await captureReleaseVisual(page, "live-interview-workspace")
  })
})
