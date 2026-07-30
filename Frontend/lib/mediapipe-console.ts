const MEDIAPIPE_INFO_MESSAGES = [
  "Created TensorFlow Lite XNNPACK delegate for CPU",
]

function consoleText(args: unknown[]): string {
  return args
    .map((value) => {
      if (value instanceof Error) return value.message
      return String(value)
    })
    .join(" ")
}

/**
 * MediaPipe's WASM runtime writes a few informational startup messages through
 * console.error. Next's development overlay treats those messages as crashes.
 * Suppress only the known informational line while the synchronous detector
 * call is running, and pass every real error through unchanged.
 */
export function withoutMediaPipeInfoNoise<T>(work: () => T): T {
  const previousError = console.error
  const filteredError = (...args: unknown[]) => {
    const message = consoleText(args)
    if (MEDIAPIPE_INFO_MESSAGES.some((item) => message.includes(item))) return
    previousError.apply(console, args)
  }

  console.error = filteredError
  try {
    return work()
  } finally {
    if (console.error === filteredError) {
      console.error = previousError
    }
  }
}
