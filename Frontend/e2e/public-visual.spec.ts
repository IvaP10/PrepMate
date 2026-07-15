import { expect, test } from "@playwright/test"

test("public landing page has stable responsive geometry", async ({ page }, testInfo) => {
  await page.goto("/")
  await expect(page.getByRole("navigation").first()).toBeVisible()
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  await testInfo.attach("landing-page", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" })
})

test("legal and status pages render without clipped content", async ({ page }) => {
  for (const route of ["/about", "/privacy", "/terms", "/status"]) {
    await page.goto(route)
    await expect(page.locator("main")).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, route).toBeLessThanOrEqual(1)
  }
})
