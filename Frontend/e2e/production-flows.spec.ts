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

  test("dashboard and Improve expose one current action while future nodes stay locked", async ({ page }) => {
    const params = new URLSearchParams({
      tab: "improve",
      mission_id: process.env.E2E_MISSION_ID!,
      roadmap_node_id: process.env.E2E_ROADMAP_NODE_ID!,
      exercise_id: process.env.E2E_EXERCISE_ID!,
    })
    await page.goto(`/?${params}`)
    await expect(page.getByText("Next best action")).toBeVisible()
    await expect(page.getByRole("button", { name: /Continue/ }).first()).toBeVisible()
    await expect(page.locator("ol button:enabled")).toHaveCount(1)
    await expect(page.getByText("Predicted", { exact: true })).toBeVisible()
    await expect(page.getByText(/Prediction confidence:/)).toBeVisible()
    await expect(page.getByText("Project ownership", { exact: true }).first()).toBeVisible()
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
    await expect(page.getByText("Attempt in progress")).toBeVisible()
    await page.getByRole("button", { name: /Answer B/ }).click()
    await page.getByLabel("Why is this stronger?").fill(
      "It starts with the direct answer, explains how the decision works, adds a concrete example, and closes with the measurable result.",
    )
    await expect(page.getByRole("button", { name: "Submit attempt" })).toBeEnabled()
    await page.getByRole("button", { name: "Submit attempt" }).click()
    await expect(page.getByText("Done correctly")).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole("button", { name: /Continue to variation|Continue to recovery/ })).toBeVisible()
    await captureReleaseVisual(page, "improve-graded-attempt")
  })

  test("interview reconnect surface never exposes coaching or scores", async ({ page }) => {
    await page.goto(`/interview/${process.env.E2E_INTERVIEW_ID}`)
    await expect(page.getByText(/interview/i).first()).toBeVisible()
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
    await page.goto(`/interview/${process.env.E2E_INTERVIEW_ID}`)
    await page.getByRole("button", { name: "Share screen" }).click()
    await expect(page.getByRole("button", { name: /End Interview|Leave interview/ })).toBeVisible({ timeout: 20_000 })
    await expect(page.getByRole("heading", { name: /Hi Release, I am Ava/i })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText("Warm-up", { exact: true })).toBeVisible()
    await expect(page.getByText(/Starting interview/i)).toBeHidden({ timeout: 20_000 })
    await expect(page.getByText(/Camera/).first()).toBeVisible()
    await expect(page.getByText(/your score|coaching feedback/i)).toHaveCount(0)
    await page.waitForTimeout(500)
    await captureReleaseVisual(page, "live-interview-workspace")
  })
})
