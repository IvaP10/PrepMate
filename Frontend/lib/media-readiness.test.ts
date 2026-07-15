import { describe, expect, it } from "vitest"

import { mediaCaptureErrorMessage } from "./media-readiness"


describe("mediaCaptureErrorMessage", () => {
  it.each([
    ["NotAllowedError", "denied"],
    ["SecurityError", "denied"],
    ["NotReadableError", "another application"],
    ["NotFoundError", "No usable microphone"],
    ["OverconstrainedError", "required capture settings"],
  ])("maps %s to actionable guidance", (name, expected) => {
    const error = new DOMException("browser detail", name)
    expect(mediaCaptureErrorMessage(error, "microphone")).toContain(expected)
    expect(mediaCaptureErrorMessage(error, "microphone")).not.toContain("browser detail")
  })
})
