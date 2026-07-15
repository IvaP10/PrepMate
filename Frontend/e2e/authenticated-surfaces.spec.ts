import { expect, test, type Page } from "@playwright/test"

function watchRuntimeFailures(page: Page) {
  const failures: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") failures.push(`console: ${message.text()}`)
  })
  page.on("pageerror", (error) => failures.push(`page: ${error.message}`))
  page.on("requestfailed", (request) => {
    if (request.url().startsWith("http://localhost:8000") || request.url().startsWith("http://127.0.0.1:8000")) {
      failures.push(`request: ${request.method()} ${request.url()} ${request.failure()?.errorText || "failed"}`)
    }
  })
  page.on("response", (response) => {
    if (response.url().includes(":8000/api/") && response.status() >= 500) {
      failures.push(`response: ${response.status()} ${response.request().method()} ${response.url()}`)
    }
  })
  return failures
}

async function openNavigation(page: Page, label: string) {
  await page.getByRole("navigation", { name: label === "Membership" || label === "Settings" ? "Account navigation" : "Main navigation" })
    .getByRole("button", { name: label, exact: true })
    .click()
  await expect(page.getByRole("heading", { name: label, exact: true }).first()).toBeVisible()
}

test.describe("authenticated application surfaces", () => {
  test.skip(process.env.E2E_REQUIRE_AUTH !== "true", "Requires a disposable authenticated fixture")

  test("all primary and account destinations render real backend state without runtime failures", async ({ page }) => {
    const failures = watchRuntimeFailures(page)
    await page.goto("/")
    await expect(page.getByRole("heading", { name: "Interview Round", exact: true }).first()).toBeVisible()

    await openNavigation(page, "Resume")
    await expect(page.getByText("Immutable interview sources")).toBeVisible()
    await expect(page.getByText("release-verification-resume.docx")).toBeVisible()
    await expect(page.getByRole("button", { name: /Backend Engineer at Example Systems/ })).toBeVisible()

    await openNavigation(page, "Interview Round")
    await expect(page.getByRole("radiogroup", { name: "Interview profile" })).toBeVisible()
    await expect(page.getByText("Past Interviews")).toBeVisible()

    await openNavigation(page, "Technical Round")
    await expect(page.getByRole("heading", { name: "Technical Rounds", exact: true })).toBeVisible()
    await expect(page.getByRole("radiogroup", { name: "Technical profile" })).toBeVisible()
    await expect(page.getByRole("button", { name: "Start Technical Round" })).toBeVisible()

    await openNavigation(page, "Performance")
    await expect(page.getByRole("group", { name: "Performance view" })).toBeVisible()
    await expect(page.getByRole("button", { name: "Interview Performance" })).toBeVisible()
    await expect(page.getByRole("button", { name: "Technical Performance" })).toBeVisible()

    await openNavigation(page, "Improve")
    await expect(page.getByText("Next best action")).toBeVisible()
    await expect(page.getByRole("button", { name: /Continue/ }).first()).toBeVisible()

    await openNavigation(page, "Membership")
    await expect(page.getByText("Plans for every stage of prep.")).toBeVisible()
    await expect(page.getByText("Free", { exact: true }).first()).toBeVisible()
    await expect(page.getByText("Pro", { exact: true }).first()).toBeVisible()
    await expect(page.getByText("Premium", { exact: true }).first()).toBeVisible()

    await openNavigation(page, "Settings")
    await expect(page.getByText("Account Information")).toBeVisible()
    expect(failures).toEqual([])
  })

  test("settings mutations, privacy export, and support submission work", async ({ page }) => {
    const failures = watchRuntimeFailures(page)
    await page.goto("/?tab=settings")
    await expect(page.getByText("Account Information")).toBeVisible()

    await page.getByRole("button", { name: "Notifications", exact: true }).click()
    await expect(page.getByText("Email Notifications")).toBeVisible()
    const weekly = page.getByRole("switch", { name: "Toggle Weekly performance summary" })
    const initialChecked = await weekly.getAttribute("aria-checked")
    await weekly.click()
    await page.getByRole("button", { name: "Save Preferences" }).click()
    await expect(page.getByText("Notification preferences saved.")).toBeVisible()
    const prefs = await page.request.get(`${process.env.E2E_API_BASE_URL}/api/profile/notification-prefs`)
    expect(prefs.ok()).toBeTruthy()
    expect((await prefs.json()).weekly_summary).toBe(initialChecked !== "true")
    await weekly.click()
    await page.getByRole("button", { name: "Save Preferences" }).click()

    await page.getByRole("button", { name: "Billing", exact: true }).click()
    await expect(page.getByText("Current Plan")).toBeVisible()
    await expect(page.getByText("Razorpay Checkout", { exact: true })).toBeVisible()
    await expect(page.getByText("No transactions yet")).toBeVisible()

    await page.getByRole("button", { name: "Privacy & Data", exact: true }).click()
    await expect(page.getByText("External AI & Third-Party Processing")).toBeVisible()
    const downloadPromise = page.waitForEvent("download")
    await page.getByRole("button", { name: "Download Data" }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(/interai.*\.json/i)

    await page.getByRole("button", { name: "Support", exact: true }).click()
    await page.getByPlaceholder(/Report page breaks/).fill("Release verification support submission")
    await page.getByPlaceholder(/Describe what happened/).fill("The release audit is verifying that support reports persist correctly.")
    await page.getByPlaceholder(/1\. Go to/).fill("1. Open settings\n2. Open support\n3. Submit the report")
    await page.getByRole("button", { name: "Submit Bug Report" }).click()
    await expect(page.getByText("Bug report submitted.")).toBeVisible()
    expect(failures).toEqual([])
  })

  test("resume job-target create, select, and delete lifecycle works", async ({ page }) => {
    const failures = watchRuntimeFailures(page)
    await page.goto("/?tab=resume")
    await expect(page.getByText("Role and full JD")).toBeVisible()
    await page.getByRole("button", { name: "Add", exact: true }).click()
    await page.getByPlaceholder("Role title").fill("Release QA Engineer")
    await page.getByPlaceholder("Company").fill("Verification Co")
    await page.getByPlaceholder("Experience level").fill("senior")
    await page.getByPlaceholder("Tech stack, comma separated").fill("Playwright, TypeScript")
    await page.getByPlaceholder("Paste the full job description").fill(
      "Own browser automation, API contract validation, accessibility checks, and production release verification.",
    )
    await page.getByRole("button", { name: "Save target" }).click()
    const temporaryTarget = page.getByRole("button", { name: /Release QA Engineer at Verification Co/ }).locator("..")
    await expect(temporaryTarget).toBeVisible()
    await expect(temporaryTarget.getByText("Selected")).toBeVisible()
    await temporaryTarget.getByRole("button", { name: "Delete job target" }).click()
    await expect(page.getByText("Release QA Engineer at Verification Co")).toHaveCount(0)
    const originalTarget = page.getByRole("button", { name: /Backend Engineer at Example Systems/ })
    await originalTarget.click()
    await expect(originalTarget.locator("..").getByText("Selected")).toBeVisible()
    expect(failures).toEqual([])
  })

  test("profile policy selection persists and can be restored", async ({ page }) => {
    const failures = watchRuntimeFailures(page)
    await page.goto("/?tab=interview")
    const profiles = page.getByRole("radiogroup", { name: "Interview profile" })
    const startupSaved = page.waitForResponse((response) => response.url().endsWith("/api/workspace/interview-profile") && response.request().method() === "PUT")
    await profiles.getByRole("radio", { name: /^Startup/ }).click()
    expect((await startupSaved).ok()).toBeTruthy()
    await expect(profiles.getByRole("radio", { name: /^Startup/ })).toBeChecked()
    const selected = await page.request.get(`${process.env.E2E_API_BASE_URL}/api/workspace/interview-profile`)
    expect((await selected.json()).profile_type).toBe("startup")
    const midTierSaved = page.waitForResponse((response) => response.url().endsWith("/api/workspace/interview-profile") && response.request().method() === "PUT")
    await profiles.getByRole("radio", { name: /^Mid Tier/ }).click()
    expect((await midTierSaved).ok()).toBeTruthy()
    await expect(profiles.getByRole("radio", { name: /^Mid Tier/ })).toBeChecked()
    expect(failures).toEqual([])
  })

  test("disposable account can sign in and log out through the UI", async ({ browser }) => {
    test.setTimeout(60_000)
    const context = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL,
      storageState: { cookies: [], origins: [] },
    })
    const page = await context.newPage()
    try {
      await page.goto("/")
      await page.getByRole("button", { name: "Log In", exact: true }).click()
      await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible()
      const failures = watchRuntimeFailures(page)
      await page.getByLabel("Email address").fill(process.env.E2E_EMAIL || "")
      await page.getByLabel("Password", { exact: true }).fill(process.env.E2E_PASSWORD || "")
      await page.getByRole("button", { name: "Sign In", exact: true }).click()
      await expect(page.getByRole("heading", { name: "Interview Round", exact: true }).first()).toBeVisible()

      await page.getByRole("button", { name: "Log out", exact: true }).click()
      await expect(page.getByRole("heading", { name: "Are you sure you want to log out?" })).toBeVisible()
      await page.getByRole("button", { name: "Log Out", exact: true }).click()
      await expect(page.getByRole("heading", { name: /Practice your next interview/ })).toBeVisible()
      expect(failures).toEqual([])
    } finally {
      await context.close()
    }
  })
})
