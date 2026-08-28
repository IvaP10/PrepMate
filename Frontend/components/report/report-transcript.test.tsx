import { describe, expect, it } from "vitest"

import { normalizeReportTranscript } from "./report-transcript"


describe("report transcript", () => {
  it("keeps persisted Interview and Technical transcript turns and removes duplicates", () => {
    const turns = normalizeReportTranscript([
      { role: "interviewer", text: "Design a rate limiter." },
      { role: "candidate", text: "I would start with a token bucket.", label: "Spoken reasoning" },
      { role: "candidate", text: "I would start with a token bucket." },
    ])

    expect(turns).toEqual([
      { role: "interviewer", text: "Design a rate limiter." },
      { role: "candidate", text: "I would start with a token bucket.", label: "Spoken reasoning" },
    ])
  })

  it("builds a legacy transcript from the report question rows", () => {
    const turns = normalizeReportTranscript([], [{
      question: "Tell me about an incident you owned.",
      response: "I led the rollback and reduced recovery time.",
    }])

    expect(turns).toEqual([
      { role: "interviewer", text: "Tell me about an incident you owned.", label: "Question" },
      { role: "candidate", text: "I led the rollback and reduced recovery time.", label: "Answer" },
    ])
  })
})
