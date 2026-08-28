"use client"

import { useState } from "react"
import { Copy, Download, ExternalLink, FolderOpen, KeyRound, Loader2, Trash2, RotateCcw } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { clearLocalCaches, deleteAllProviderKeys, deleteResumeData, deleteSessionHistory, downloadUserDataExport, fetchRedactedDiagnostics, wipeAllLocalData } from "@/lib/api"

export function DataPrivacy() {
  const [busy, setBusy] = useState<string | null>(null)

  const run = async (key: string, action: () => Promise<void>, success: string) => {
    setBusy(key)
    try {
      await action()
      toast.success(success)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "The local data action failed.")
    } finally {
      setBusy(null)
    }
  }

  const confirmAndRun = (key: string, message: string, action: () => Promise<void>, success: string) => {
    if (typeof window !== "undefined" && window.confirm(message)) {
      void run(key, action, success)
    }
  }

  const openDataFolder = async () => {
    const desktop = typeof window !== "undefined" ? window.prepmateDesktop : undefined
    if (!desktop?.openDataFolder) {
      toast.info("The local data folder is available in your operating-system application-data directory.")
      return
    }
    const result = await desktop.openDataFolder()
    if (!result?.success) toast.error(result?.error || "Could not open the local data folder.")
  }

  const copyDiagnostics = async () => {
    await run("diagnostics", async () => {
      const diagnostics = await fetchRedactedDiagnostics()
      await navigator.clipboard.writeText(JSON.stringify(diagnostics, null, 2))
    }, "Redacted diagnostics copied.")
  }

  return (
    <section className="dashboard-card space-y-5">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Data &amp; privacy</p>
        <h2 className="mt-2 text-xl font-semibold tracking-tight text-foreground">Control your local data</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          PrepMate stores your resumes, job profiles, answers, reports, and preferences on this computer. AI prompts leave the device only for the provider you select.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => void run("export", downloadUserDataExport, "Readable data export downloaded.")} disabled={busy !== null}>
          {busy === "export" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          Export my data
        </Button>
        <Button variant="outline" onClick={() => void openDataFolder()} disabled={busy !== null}>
          <FolderOpen className="h-4 w-4" />
          Open local data folder
        </Button>
        <Button variant="outline" onClick={() => void copyDiagnostics()} disabled={busy !== null}>
          {busy === "diagnostics" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Copy className="h-4 w-4" />}
          Copy redacted diagnostics
        </Button>
        <Button variant="outline" onClick={() => confirmAndRun("keys", "Remove every saved provider key from the operating-system keychain?", deleteAllProviderKeys, "All provider keys were removed.")} disabled={busy !== null}>
          {busy === "keys" ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
          Remove all provider keys
        </Button>
        <Button variant="outline" onClick={() => confirmAndRun("cache", "Remove downloaded models and local caches? Your interview history will remain.", async () => { await clearLocalCaches() }, "Downloaded models and caches were removed.")} disabled={busy !== null}>
          {busy === "cache" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
          Clear models and caches
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-border/60 bg-secondary/20 p-4">
          <p className="text-sm font-semibold text-foreground">Delete interview history</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">Removes completed interviews, reports, performance evidence, and Improve history. Your provider settings remain.</p>
          <Button className="mt-3" variant="outline" onClick={() => confirmAndRun("history", "Delete all interview history and its performance evidence? This cannot be undone.", async () => { await deleteSessionHistory() }, "Interview history deleted.")} disabled={busy !== null}>
            {busy === "history" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
            Delete history
          </Button>
        </div>
        <div className="rounded-lg border border-border/60 bg-secondary/20 p-4">
          <p className="text-sm font-semibold text-foreground">Delete resumes and profile files</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">Removes imported resume versions, profile data, and saved setup snapshots. Past interview reports and derived session evidence remain until you delete interview history.</p>
          <Button className="mt-3" variant="outline" onClick={() => confirmAndRun("resume", "Delete all imported resumes and clear the active resume?", async () => { await deleteResumeData() }, "Resumes removed.")} disabled={busy !== null}>
            {busy === "resume" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
            Delete resumes
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
        <p className="text-sm font-semibold text-foreground">Complete local wipe</p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">Deletes the SQLite database, preferences, downloaded model/cache folders, provider keys, and any legacy local data copied during the rename. The empty schema is recreated so PrepMate can start fresh.</p>
        <Button className="mt-3" variant="destructive" onClick={() => confirmAndRun("wipe", "This permanently removes all PrepMate data, provider keys, caches, and migrated legacy data. Continue?", async () => { await wipeAllLocalData() }, "All local PrepMate data was wiped.")} disabled={busy !== null}>
          {busy === "wipe" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
          Wipe everything
        </Button>
      </div>

      <p className="flex items-start gap-2 text-xs leading-5 text-muted-foreground">
        <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        Exports are readable JSON files. Protect them like a resume, and remember that losing the operating-system data-encryption key can make an existing database unreadable.
      </p>
    </section>
  )
}
