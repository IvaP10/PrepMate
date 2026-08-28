import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const performanceSource = readFileSync(
  fileURLToPath(new URL("./performance-content.tsx", import.meta.url)),
  "utf8",
)

const appShellSource = readFileSync(
  fileURLToPath(new URL("../app-shell.tsx", import.meta.url)),
  "utf8",
)

describe("Performance and Improve navigation contracts", () => {
  it("keeps Improve permanently available in the workspace", () => {
    expect(appShellSource).toContain('{ icon: Target, label: "Improve", id: "improve" }')
    expect(appShellSource).toContain("const navigationItems = primaryNavItems")
    expect(appShellSource).not.toContain('item.id !== "improve"')
    expect(appShellSource).not.toContain('if (nav === "improve"')
    expect(appShellSource).not.toContain("if (!improveAvailable)")
  })

  it("shows combined Performance while individual reports stay in the round tabs", () => {
    expect(performanceSource).toContain("Combined Performance")
    expect(performanceSource).toContain("Reports combined")
    expect(performanceSource).toContain("Where You Need Work")
    expect(performanceSource).toContain("What Is Going Well")
    expect(performanceSource).toContain("Evidence combined from reports")
    expect(performanceSource).toContain("Open an individual report from the")
    expect(performanceSource).not.toContain("Report scope")
    expect(performanceSource).not.toContain("View full report")
    expect(performanceSource).not.toContain("RoundHistorySection")
    expect(performanceSource).not.toContain("onOpenReport")
    expect(performanceSource).not.toContain("useRouter")
    expect(performanceSource).not.toContain("No grounded mistakes were recorded")
  })
})
