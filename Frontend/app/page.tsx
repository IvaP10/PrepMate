"use client"

import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { AppShell } from "@/components/app-shell"
import { ResumeProvider } from "@/context/resume-context"
import { useTheme } from "@/hooks/use-theme"
import { readImproveTarget } from "@/lib/improve-navigation"

function LocalWorkspace() {
  const params = useSearchParams()
  const { theme, toggleTheme } = useTheme()
  const initialTab = params.get("tab") || "interview"
  const improveTarget = initialTab === "improve" ? readImproveTarget(params) : null

  return (
    <ResumeProvider userId="local-prepmate-user">
      <AppShell
        theme={theme}
        onToggleTheme={toggleTheme}
        initialTab={initialTab}
        initialImproveTarget={improveTarget}
      />
    </ResumeProvider>
  )
}

export default function Home() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background" />}>
      <LocalWorkspace />
    </Suspense>
  )
}
