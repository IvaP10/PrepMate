"use client"
import { useEffect } from "react"
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
  }, [error])
  return null
}
