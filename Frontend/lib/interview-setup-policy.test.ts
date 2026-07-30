import { describe, expect, it } from "vitest"

import { requiresSavedJobProfile } from "./interview-setup-policy"


describe("interview setup start policy", () => {
  it.each(["top_tier", "mid_tier", "startup"])(
    "allows the %s preset to start from confirmed resume context",
    (profileType) => {
      expect(requiresSavedJobProfile(profileType)).toBe(false)
    },
  )

  it("keeps Custom tied to a saved role and full job description", () => {
    expect(requiresSavedJobProfile("custom")).toBe(true)
  })
})
