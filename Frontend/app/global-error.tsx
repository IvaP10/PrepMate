"use client"
import { useEffect } from "react"
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
  }, [error])
  return (
    <html>
      <body>
        <div style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          height: "100vh",
          gap: "16px",
          fontFamily: "system-ui, sans-serif",
          background: "#0a0a0a",
          color: "#fff",
        }}>
          <h2 style={{ fontSize: "18px", fontWeight: 600 }}>Something went wrong</h2>
          <button
            onClick={reset}
            style={{
              padding: "8px 20px",
              borderRadius: "8px",
              border: "1px solid #333",
              background: "#1a1a1a",
              color: "#fff",
              cursor: "pointer",
              fontSize: "14px",
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  )
}
