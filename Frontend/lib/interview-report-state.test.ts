import { describe, expect, it } from "vitest"

import { interviewQuestionStatus, interviewReportAvailability } from "./interview-report-state"

describe("interview report availability", () => {
  it("keeps active and recovering attempts out of report polling", () => {
    expect(interviewReportAvailability("in_progress", "active")).toBe("active")
    expect(interviewReportAvailability("recovering", "recovering")).toBe("recovering")
  })

  it("marks cancelled or incomplete attempts as having no official report", () => {
    expect(interviewReportAvailability("cancelled", "incomplete")).toBe("incomplete")
    expect(interviewReportAvailability("failed", "incomplete")).toBe("incomplete")
  })

  it("allows completed analysis states to load or poll the report", () => {
    expect(interviewReportAvailability("analysis_pending", "completed")).toBe("available")
    expect(interviewReportAvailability("report_ready", "completed")).toBe("available")
    expect(interviewReportAvailability("execution_pending", "active")).toBe("available")
  })

  it("derives a missing legacy status from persisted answer evidence", () => {
    expect(interviewQuestionStatus({
      response: "I owned the API rollout and reduced p95 latency by 38 percent.",
      score: 82,
    })).toBe("Completed")
    expect(interviewQuestionStatus({
      response: "I owned the API rollout.",
      status: "Not Answered",
      score: 82,
    })).toBe("Completed")
    expect(interviewQuestionStatus({ response: "" })).toBe("Not Answered")
  })
})
