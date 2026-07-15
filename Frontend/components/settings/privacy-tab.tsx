"use client"
import { useState } from "react"
import Link from "next/link"
import { Download, Shield, Loader2, ExternalLink } from "lucide-react"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"
import { exportUserData } from "@/lib/api"

export function PrivacyTab() {
  const [exporting, setExporting] = useState(false)

  const handleExport = async () => {
    setExporting(true)
    try {
      await exportUserData()
      toast.success("Data exported. Check your downloads.")
    } catch (e: any) { toast.error(e?.message || "Failed to export data.") }
    finally { setExporting(false) }
  }

  return (
    <div className="space-y-6">

      <div className="dashboard-card ring-1 ring-primary/15">
        <div className="mb-3 flex items-center gap-2">
          <ExternalLink className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold text-foreground">External AI & Third-Party Processing</h3>
        </div>
        <div className="space-y-3 text-sm leading-6 text-muted-foreground">
          <p>
            InterAI sends certain data to external providers to run core features, including OpenAI,
            Razorpay, Google Sign-In, code-execution services, and observability tools.
          </p>
          <p>
            Before text is sent to external language models, we apply automated redaction to remove
            common identifiers such as email, phone, and social links.{" "}
            <strong className="font-semibold text-foreground">
              This redaction is best-effort only and is not guaranteed.
            </strong>{" "}
            Names, employer or school names, locations, voice audio, interview answers, resume
            content, code, and other details may still reach external providers if our pipeline
            misses them or if they are needed for the feature to work.
          </p>
          <p>
            By using InterAI, you acknowledge that information you submit may be processed by these
            third parties under their own privacy policies. Do not upload or enter data you are not
            authorized to share or that you would not want sent externally.
          </p>
          <Link
            href="/privacy#ai-processing"
            className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
          >
            Read the full Privacy Policy
            <ExternalLink className="h-3.5 w-3.5" />
          </Link>
        </div>
      </div>

      <div className="dashboard-card">
        <div className="mb-3 flex items-center gap-2">
          <Shield className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold text-foreground">What We Store</h3>
        </div>
        <p className="text-sm leading-6 text-muted-foreground">
          InterAI stores your resume data, interview transcripts, scores, and coaching feedback to
          personalize practice and generate performance insights. Your account data is encrypted at
          rest where configured. You can export your data at any time from this page, or manage your
          account settings from the Account tab.
        </p>
      </div>


      <div className="dashboard-card">
        <h3 className="mb-1 text-sm font-semibold text-foreground">Download My Data</h3>
        <p className="mb-4 text-xs text-muted-foreground">
          Export all your sessions, scores, answers, and profile information as a JSON file.
        </p>
        <Button variant="outline" className="gap-2" onClick={handleExport} disabled={exporting}>
          {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          {exporting ? "Exporting..." : "Download Data"}
        </Button>
      </div>
    </div>
  )
}
