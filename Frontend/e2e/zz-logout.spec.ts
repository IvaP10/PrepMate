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
  return failures
}

test.describe("final authenticated session check", () => {
  test.skip(process.env.E2E_REQUIRE_AUTH !== "true", "Requires a disposable authenticated fixture")

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
      expect(failures).toEqual([])
      await page.getByRole("button", { name: "Log Out", exact: true }).click()
      await expect(page.getByRole("heading", { name: /AI mock interviews tailored to your resume/ })).toBeVisible()
    } finally {
      await context.close()
    }
  })
})
