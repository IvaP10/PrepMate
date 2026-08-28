import { describe, expect, it } from "vitest"

import { questionScoreLabel } from "./question-deep-dive"


describe("question score truth", () => {
  it("does not render a missing or ungradable assessment as zero", () => {
    expect(questionScoreLabel(null, "Incomplete")).toBe("Unable to Evaluate")
    expect(questionScoreLabel(undefined, "Unable to Evaluate")).toBe("Unable to Evaluate")
  })

  it("keeps explicit numeric and unanswered-zero outcomes", () => {
    expect(questionScoreLabel(7.6, "Completed")).toBe("8/10")
    expect(questionScoreLabel(null, "Not Answered")).toBe("0/10")
  })
})
