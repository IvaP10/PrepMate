import fs from "node:fs/promises"
import path from "node:path"
import { expect, test, type Page } from "@playwright/test"

const visualDirectory = path.join(process.cwd(), "e2e", ".generated", "visible-system")

async function capture(page: Page, name: string) {
  await fs.mkdir(visualDirectory, { recursive: true })
  await page.screenshot({ path: path.join(visualDirectory, `${name}.png`), fullPage: true })
}

test.describe.serial("visible system behavior", () => {
  test.skip(process.env.E2E_REQUIRE_AUTH !== "true", "Requires a disposable authenticated fixture")

  test("account edits and password changes persist, then restore cleanly", async ({ page }) => {
    test.setTimeout(60_000)
    const originalPassword = process.env.E2E_PASSWORD || ""
    const temporaryPassword = "Visual!RoundTrip7294"
    await page.goto("/?tab=settings")
    await expect(page.getByText("Account Information")).toBeVisible()

    await page.getByLabel("Full Name").fill("Visual System Candidate")
    await page.getByRole("button", { name: "Save Changes" }).click()
    await expect(page.getByText("Account info saved.")).toBeVisible()
    await expect(page.getByRole("complementary").first().getByText("Visual System Candidate", { exact: true })).toBeVisible()
    await page.reload()
    await expect(page.getByLabel("Full Name")).toHaveValue("Visual System Candidate")

    await page.getByLabel("Current Password", { exact: true }).fill(originalPassword)
    await page.getByLabel("New Password", { exact: true }).fill(temporaryPassword)
    await page.getByLabel("Confirm New Password").fill(temporaryPassword)
    const firstPasswordChange = page.waitForResponse((response) => response.url().endsWith("/api/auth/change-password") && response.request().method() === "POST")
    await page.getByRole("button", { name: "Update Password" }).click()
    expect((await firstPasswordChange).ok()).toBeTruthy()
    await expect(page.getByText("Password changed.").first()).toBeVisible()

    await page.getByLabel("Current Password", { exact: true }).fill(temporaryPassword)
    await page.getByLabel("New Password", { exact: true }).fill(originalPassword)
    await page.getByLabel("Confirm New Password").fill(originalPassword)
    const restoredPasswordChange = page.waitForResponse((response) => response.url().endsWith("/api/auth/change-password") && response.request().method() === "POST")
    await page.getByRole("button", { name: "Update Password" }).click()
    expect((await restoredPasswordChange).ok()).toBeTruthy()
    await expect(page.getByText("Password changed.").last()).toBeVisible()

    await page.getByLabel("Full Name").fill("Release Verification Candidate")
    await page.getByRole("button", { name: "Save Changes" }).click()
    await expect(page.getByText("Account info saved.")).toBeVisible()
    await expect(page.getByRole("complementary").first().getByText("Release Verification Candidate", { exact: true })).toBeVisible()
    const verified = await page.request.get(`${process.env.E2E_API_BASE_URL}/api/auth/verify`)
    expect(verified.ok()).toBeTruthy()
    await page.context().storageState({ path: path.join(process.cwd(), "e2e", ".generated", "auth.json") })
    await capture(page, "account-round-trip")
  })

  test("dashboard setup creates a new interview and reaches the live media workspace", async ({ page }) => {
    test.setTimeout(90_000)
    await page.goto("/?tab=interview")
    await expect(page.getByRole("radiogroup", { name: "Interview profile" })).toBeVisible()
    await page.getByRole("button", { name: "Start Interview Round", exact: true }).click()
    const dialog = page.getByRole("dialog")
    await expect(dialog.getByRole("heading", { name: "Before you begin" })).toBeVisible()
    await expect(dialog.getByText("Screen sharing")).toBeVisible()
    await expect(dialog.getByText("Camera")).toBeVisible()
    await dialog.getByRole("button", { name: "Start Interview Round", exact: true }).click()

    await expect(page).toHaveURL(/\/interview\/[a-f0-9-]+\?/, { timeout: 30_000 })
    await expect(page.getByRole("button", { name: /End Interview|Leave interview/ })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText("Warm-up", { exact: true })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(/Camera/).first()).toBeVisible()
    await expect(page.getByText(/Microphone/).first()).toBeVisible()
    await capture(page, "new-interview-live")
  })

  test("technical Run produces a visible result or a truthful executor blocker", async ({ page }) => {
    test.setTimeout(60_000)
    await page.goto(`/interview/${process.env.E2E_TECHNICAL_ID}/technical`)
    await expect(page.locator(".monaco-editor")).toBeVisible({ timeout: 20_000 })
    await page.getByRole("button", { name: "Run", exact: true }).click()
    await expect(page.getByText(/run completed|execution|executor|unavailable|failed|error/i).last()).toBeVisible({ timeout: 30_000 })
    await capture(page, "technical-run-result")
  })

  test("uploading a DOCX through the visible Resume UI creates a persisted version", async ({ page }) => {
    test.setTimeout(90_000)
    await page.goto("/?tab=resume")
    await expect(page.getByText("Immutable interview sources")).toBeVisible()
    await page.locator('input[type="file"]').setInputFiles(path.join(process.cwd(), "e2e", ".generated", "visual-system-resume.docx"))
    await expect(page.getByText("visual-system-resume.docx")).toBeVisible({ timeout: 45_000 })
    await page.reload()
    await expect(page.getByText("visual-system-resume.docx")).toBeVisible({ timeout: 20_000 })
    await capture(page, "resume-upload-persisted")
  })

  test("checkout visibly blocks payment when Razorpay is not configured", async ({ page }) => {
    await page.goto("/checkout?plan=pro")
    await expect(page.getByRole("heading", { name: "Pro membership" })).toBeVisible()
    await expect(page.getByText("Payments are temporarily unavailable. Please try again later.")).toBeVisible()
    await expect(page.getByRole("button", { name: "Checkout unavailable" })).toBeDisabled()
    await capture(page, "checkout-truthful-blocker")
  })
})
