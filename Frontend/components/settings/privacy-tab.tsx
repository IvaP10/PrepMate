"use client"
import { useState } from "react"
import { Download, Trash2, Shield, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog"
import { exportUserData, deleteSessionHistory } from "@/lib/api"

export function PrivacyTab() {
  const [exporting, setExporting] = useState(false)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [deletingHistory, setDeletingHistory] = useState(false)

  const handleExport = async () => {
    setExporting(true)
    try {
      await exportUserData()
      toast.success("Data exported — check your downloads.")
    } catch (e: any) { toast.error(e?.message || "Failed to export data.") }
    finally { setExporting(false) }
  }

  const handleDeleteHistory = async () => {
    setDeletingHistory(true)
    try {
      await deleteSessionHistory()
      toast.success("All session history deleted.")
      setShowDeleteDialog(false)
    } catch (e: any) { toast.error(e?.message || "Failed to delete session history.") }
    finally { setDeletingHistory(false) }
  }

  return (
    <div className="space-y-6">
      
      <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
        <div className="mb-3 flex items-center gap-2">
          <Shield className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold text-foreground">What We Store</h3>
        </div>
        <p className="text-sm leading-6 text-muted-foreground">
          InterAI stores your resume data, interview recordings (as text transcripts), scores, and coaching feedback.
          We use this data solely to personalise your practice experience and generate performance insights.
          Your data is encrypted at rest and is never shared with third parties.
          You can export or delete it at any time from this page.
        </p>
      </div>

      
      <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
        <h3 className="mb-1 text-sm font-semibold text-foreground">Download My Data</h3>
        <p className="mb-4 text-xs text-muted-foreground">
          Export all your sessions, scores, answers, and profile information as a JSON file.
        </p>
        <Button variant="outline" className="gap-2" onClick={handleExport} disabled={exporting}>
          {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          {exporting ? "Exporting..." : "Download Data"}
        </Button>
      </div>

      
      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-6">
        <h3 className="mb-1 text-sm font-semibold text-amber-600 dark:text-amber-400">Delete Session History</h3>
        <p className="mb-4 text-xs text-muted-foreground">
          This keeps your account but permanently wipes all practice data, interview sessions, and scores.
          Your profile, resume, and job profiles will remain.
        </p>
        <Button variant="outline" className="gap-2 border-amber-500/30 text-amber-600 dark:text-amber-400 hover:bg-amber-500/10" onClick={() => setShowDeleteDialog(true)}>
          <Trash2 className="h-4 w-4" /> Delete All Sessions
        </Button>
      </div>

      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent className="max-w-sm border-border bg-card">
          <DialogHeader>
            <DialogTitle className="text-lg font-bold text-foreground">Delete all session history?</DialogTitle>
            <DialogDescription className="mt-2 text-sm text-muted-foreground">
              This will permanently delete all your interviews, questions, responses, and scores. Your account and profile will remain intact.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="mt-4 flex gap-3">
            <Button variant="outline" className="flex-1" onClick={() => setShowDeleteDialog(false)} disabled={deletingHistory}>Cancel</Button>
            <Button variant="destructive" className="flex-1 gap-2" onClick={handleDeleteHistory} disabled={deletingHistory}>
              {deletingHistory ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              Delete All
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
