import { expect, test, type Locator, type Page } from "@playwright/test"

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

async function selectRoundProfile(page: Page, group: Locator, name: RegExp) {
  const choice = group.getByRole("radio", { name })
  if (await choice.isChecked()) return
  const saved = page.waitForResponse((response) => (
    response.url().endsWith("/api/workspace/interview-profile") &&
    response.request().method() === "PUT"
  ))
  await choice.click()
  expect((await saved).ok()).toBeTruthy()
  await expect(choice).toBeChecked()
}

async function openRoundSetup(page: Page, tab: "interview" | "technical", groupName: "Interview profile" | "Technical profile") {
  await page.goto(`/?tab=${tab}`)
  const group = page.getByRole("radiogroup", { name: groupName })
  await expect(group).toBeVisible()
  const profileResponse = await page.request.get(
    `${process.env.E2E_API_BASE_URL}/api/workspace/interview-profile`,
  )
  expect(profileResponse.ok()).toBeTruthy()
  const persistedProfile = await profileResponse.json()
  const persistedChoices: Record<string, RegExp> = {
    top_tier: /Top Tier/,
    mid_tier: /Mid Tier/,
    startup: /Startup/,
    custom: /Custom/,
  }
  const persistedChoice = persistedChoices[String(persistedProfile.profile_type)]
  if (!persistedChoice) throw new Error(`Unexpected persisted profile: ${persistedProfile.profile_type}`)
  await expect(group.getByRole("radio", { name: persistedChoice })).toBeChecked()
  return group
}

test.describe("authenticated application surfaces", () => {
  test.skip(process.env.E2E_REQUIRE_AUTH !== "true", "Requires a disposable authenticated fixture")

  test("all primary and account destinations render real backend state without runtime failures", async ({ page }) => {
    const failures = watchRuntimeFailures(page)
    await page.goto("/")
    await expect(page.getByRole("heading", { name: "Interview Round", exact: true }).first()).toBeVisible()

    await openNavigation(page, "Resume")
    await expect(page.getByRole("heading", { name: "Resume versions", exact: true })).toBeVisible()
    await expect(page.getByText("release-verification-resume.docx")).toBeVisible()
    await expect(page.getByRole("button", { name: /Backend Engineer at Example Systems/ })).toBeVisible()
    const currentResumePreview = page.getByRole("heading", { name: "Current Resume Preview", exact: true }).locator("..").locator("..")
    await expect(currentResumePreview).toBeVisible()
    await expect(currentResumePreview.getByRole("heading", { name: "Personal Profile", exact: true })).toBeVisible()
    await expect(currentResumePreview.getByRole("heading", { name: "Education", exact: true })).toBeVisible()
    await expect(currentResumePreview.getByRole("heading", { name: "Technical Skills", exact: true })).toBeVisible()
    await page.getByRole("button", { name: "Add profile", exact: true }).click()
    await expect(page.getByPlaceholder("Role title", { exact: true })).toBeVisible()
    await expect(page.getByPlaceholder("Company", { exact: true })).toBeVisible()
    await expect(page.getByPlaceholder("Paste the full job description", { exact: true })).toBeVisible()
    await expect(page.getByPlaceholder("Experience level", { exact: true })).toHaveCount(0)
    await expect(page.getByPlaceholder("Tech stack, comma separated", { exact: true })).toHaveCount(0)

    await openNavigation(page, "Interview Round")
    await expect(page.getByText("Company environment", { exact: true })).toBeVisible()
    await expect(page.getByRole("heading", { name: "Interview Round", exact: true, level: 3 })).toBeVisible()
    const interviewProfiles = page.getByRole("radiogroup", { name: "Interview profile" })
    await expect(interviewProfiles).toBeVisible()
    await expect(interviewProfiles.getByRole("radio", { name: /Top Tier/ })).toBeVisible()
    await expect(interviewProfiles.getByRole("radio", { name: /Mid Tier/ })).toBeVisible()
    await expect(interviewProfiles.getByRole("radio", { name: /Startup/ })).toBeVisible()
    await expect(interviewProfiles.getByRole("radio", { name: /Custom/ })).toBeVisible()
    await expect(page.getByText("Past Interviews")).toBeVisible()

    await openNavigation(page, "Technical Round")
    await expect(page.getByText("Company environment", { exact: true })).toBeVisible()
    await expect(page.getByRole("heading", { name: "Technical Round", exact: true, level: 3 })).toBeVisible()
    await expect(page.getByRole("heading", { name: "Technical Rounds", exact: true })).toBeVisible()
    const technicalProfiles = page.getByRole("radiogroup", { name: "Technical profile" })
    await expect(technicalProfiles).toBeVisible()
    await expect(technicalProfiles.getByRole("radio", { name: /Top Tier/ })).toBeVisible()
    await expect(technicalProfiles.getByRole("radio", { name: /Mid Tier/ })).toBeVisible()
    await expect(technicalProfiles.getByRole("radio", { name: /Startup/ })).toBeVisible()
    await expect(technicalProfiles.getByRole("radio", { name: /Custom/ })).toBeVisible()
    await expect(page.getByRole("button", { name: "Start Technical Round" })).toBeVisible()

    await openNavigation(page, "Performance")
    const performanceMode = page.getByRole("group", { name: "Performance round type" })
    await expect(performanceMode.getByRole("button", { name: "Interview Round", exact: true })).toHaveAttribute("aria-pressed", "true")
    await expect(page.getByTestId("performance-page")).toHaveAttribute("data-performance-mode", "interview")
    await expect(page.getByRole("heading", { name: "Interview Performance", exact: true })).toHaveCount(0)
    await expect(page.getByRole("heading", { name: "Technical Performance", exact: true })).toHaveCount(0)
    await performanceMode.getByRole("button", { name: "Technical Round", exact: true }).click()
    await expect(page.getByTestId("performance-page")).toHaveAttribute("data-performance-mode", "coding")
    await expect(page.getByRole("heading", { name: "Technical Performance", exact: true })).toHaveCount(0)
    await expect(page.getByRole("heading", { name: "Round history", exact: true })).toHaveCount(0)

    await openNavigation(page, "Improve")
    const improveMode = page.getByRole("group", { name: "Improve pathway mode" })
    await expect(improveMode.getByRole("button", { name: "Interview Round", exact: true })).toHaveAttribute("aria-pressed", "true")
    await expect(page.getByText("Interview learning path", { exact: true })).toBeVisible()
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

  test("profiles can be saved and deleted from interview and technical setup", async ({ page }) => {
    const failures = watchRuntimeFailures(page)
    const interviewProfiles = await openRoundSetup(page, "interview", "Interview profile")
    await selectRoundProfile(page, interviewProfiles, /Mid Tier/)
    await expect(page.getByText("Saved roles and full job descriptions", { exact: true })).toHaveCount(0)
    await selectRoundProfile(page, interviewProfiles, /Custom/)
    await expect(page.getByText("Saved roles and full job descriptions", { exact: true })).toBeVisible()
    await page.getByRole("button", { name: "Add another", exact: true }).click()
    await page.getByPlaceholder("Backend Engineer").fill("Release QA Engineer")
    await page.getByPlaceholder("Company name").fill("Verification Co")
    await page.getByPlaceholder("Paste the complete responsibilities, requirements, and preferred skills.").fill(
      "Own browser automation, API contract validation, accessibility checks, and production release verification.",
    )
    await page.getByRole("button", { name: "Save job target" }).click()
    const selectedInterviewTarget = page.getByRole("button", { name: /Release QA Engineer at Verification Co/ }).locator("..")
    await expect(selectedInterviewTarget).toBeVisible()
    await expect(page.getByRole("button", { name: "Start Interview Round" })).toBeEnabled()
    await selectedInterviewTarget.getByRole("button", { name: "Delete Release QA Engineer job target" }).click()
    await expect(page.getByRole("heading", { name: "Delete job target?" })).toBeVisible()
    await page.getByRole("button", { name: "Delete", exact: true }).click()
    await expect(page.getByText("Release QA Engineer at Verification Co")).toHaveCount(0)

    const technicalProfiles = await openRoundSetup(page, "technical", "Technical profile")
    await selectRoundProfile(page, technicalProfiles, /Mid Tier/)
    await expect(page.getByText("Saved roles and full job descriptions", { exact: true })).toHaveCount(0)
    await selectRoundProfile(page, technicalProfiles, /Custom/)
    await expect(page.getByText("Saved roles and full job descriptions", { exact: true })).toBeVisible()
    await page.getByRole("button", { name: "Add another", exact: true }).click()
    await page.getByPlaceholder("Backend Engineer").fill("Technical Cleanup Engineer")
    await page.getByPlaceholder("Company name").fill("Verification Co")
    await page.getByPlaceholder("Paste the complete responsibilities, requirements, and preferred skills.").fill(
      "Build reliable technical interview systems, validate data structures, and maintain backend services.",
    )
    await page.getByRole("button", { name: "Save job target" }).click()
    const selectedTechnicalTarget = page.getByRole("button", { name: /Technical Cleanup Engineer at Verification Co/ }).locator("..")
    await expect(selectedTechnicalTarget).toBeVisible()
    await expect(page.getByRole("button", { name: "Start Technical Round" })).toBeEnabled()
    await selectedTechnicalTarget.getByRole("button", { name: "Delete Technical Cleanup Engineer job target" }).click()
    await expect(page.getByRole("heading", { name: "Delete job target?" })).toBeVisible()
    await page.getByRole("button", { name: "Delete", exact: true }).click()
    await expect(page.getByText("Technical Cleanup Engineer at Verification Co")).toHaveCount(0)

    expect(failures).toEqual([])
  })

  test("interview context selection persists and can be restored", async ({ page }) => {
    const failures = watchRuntimeFailures(page)
    const profiles = await openRoundSetup(page, "interview", "Interview profile")
    await selectRoundProfile(page, profiles, /Mid Tier/)
    await selectRoundProfile(page, profiles, /Custom/)
    await expect(profiles.getByRole("radio", { name: /Custom/ })).toBeChecked()
    const selected = await page.request.get(`${process.env.E2E_API_BASE_URL}/api/workspace/interview-profile`)
    expect((await selected.json()).profile_type).toBe("custom")
    await selectRoundProfile(page, profiles, /Mid Tier/)
    await expect(profiles.getByRole("radio", { name: /Mid Tier/ })).toBeChecked()
    expect(failures).toEqual([])
  })

})
