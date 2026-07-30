import { afterEach, describe, expect, it, vi } from "vitest"

import { withoutMediaPipeInfoNoise } from "./mediapipe-console"


afterEach(() => {
  vi.restoreAllMocks()
})

describe("withoutMediaPipeInfoNoise", () => {
  it("filters the TensorFlow startup info but preserves real errors", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})

    const result = withoutMediaPipeInfoNoise(() => {
      console.error("INFO: Created TensorFlow Lite XNNPACK delegate for CPU.")
      console.error("Face detector failed")
      return "done"
    })

    expect(result).toBe("done")
    expect(errorSpy).toHaveBeenCalledOnce()
    expect(errorSpy).toHaveBeenCalledWith("Face detector failed")
  })

  it("restores console.error when detection throws", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})

    expect(() =>
      withoutMediaPipeInfoNoise(() => {
        throw new Error("detection failed")
      })
    ).toThrow("detection failed")

    console.error("after")
    expect(errorSpy).toHaveBeenCalledWith("after")
  })
})
