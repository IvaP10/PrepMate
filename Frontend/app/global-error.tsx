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
          background: "#0B0F0E",
          color: "#F3F6F5",
        }}>
          <h2 style={{ fontSize: "18px", fontWeight: 600 }}>Something went wrong</h2>
          <button
            onClick={reset}
            style={{
              padding: "8px 20px",
              borderRadius: "8px",
              border: "1px solid #2E3835",
              background: "#171D1B",
              color: "#F3F6F5",
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
