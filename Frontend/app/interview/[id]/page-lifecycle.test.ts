import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const source = readFileSync(
  fileURLToPath(new URL("./page.tsx", import.meta.url)),
  "utf8",
)

describe("normal interview browser lifecycle", () => {
  it("treats refresh and tab lifecycle changes as recoverable interruptions", () => {
    expect(source).not.toContain('addEventListener("pagehide"')
    expect(source).not.toContain("abandonInterviewSession")
    expect(source).toContain('addEventListener("beforeunload"')
  })
})
