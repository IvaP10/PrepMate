"use client"

import { useEffect, useState } from "react"
import { Activity, AlertCircle, CheckCircle2 } from "lucide-react"
import { API_CONFIG } from "@/lib/config"

type StatusPayload = {
  status: string
  updated_at: string
  components: Record<string, string>
}

export default function StatusPage() {
  const [status, setStatus] = useState<StatusPayload | null>(null)

  useEffect(() => {
    const apiBase = API_CONFIG.BASE_URL
    fetch(`${apiBase.replace(/\/api$/, "")}/api/status`, { cache: "no-store" })
      .then((response) => response.json())
      .then(setStatus)
      .catch(() => setStatus({ status: "degraded", updated_at: new Date().toISOString(), components: { api: "degraded" } }))
  }, [])

  const ok = status?.status === "healthy"

  return (
    <main className="min-h-screen bg-background p-6 text-foreground">
      <div className="mx-auto max-w-3xl">
        <div className="mb-6 flex items-center gap-3">
          <Activity className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-semibold">System Status</h1>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-3">
            {ok ? <CheckCircle2 className="h-5 w-5 text-emerald-500" /> : <AlertCircle className="h-5 w-5 text-amber-500" />}
            <div>
              <p className="font-medium">{ok ? "All core systems operational" : "One or more systems are degraded"}</p>
              <p className="text-sm text-muted-foreground">Updated {status?.updated_at ? new Date(status.updated_at).toLocaleString() : "loading..."}</p>
            </div>
          </div>
        </div>
        <div className="mt-4 space-y-2">
          {Object.entries(status?.components || {}).map(([name, value]) => (
            <div key={name} className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3">
              <span className="capitalize">{name.replace(/_/g, " ")}</span>
              <span className={value === "operational" ? "text-emerald-500" : "text-amber-500"}>{value}</span>
            </div>
          ))}
        </div>
      </div>
    </main>
  )
}
