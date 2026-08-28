import Link from "next/link"

export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-background px-6 py-12 text-foreground">
      <article className="mx-auto max-w-3xl space-y-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Privacy</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">How PrepMate handles data</h1>
        </div>
        <section className="space-y-3 text-sm leading-7 text-muted-foreground">
          <p>PrepMate has no account system, hosted application database, analytics, advertising, payment flow, or browser edition. Your local database, resumes, answers, reports, and settings stay on this computer.</p>
          <p>When you use an AI feature, the selected provider receives the prompt context needed for that feature. API keys stay in the operating-system keychain. Review the provider&apos;s retention terms before sending sensitive material.</p>
          <p>Camera, microphone, and screen coaching are optional and start only after you choose them. The app does not download speech or vision models. Technical code execution is enabled only when the macOS Seatbelt sandbox is detected.</p>
          <p>Use Settings → Data &amp; privacy to export or delete data, clear downloaded assets, remove provider keys, open the local data directory, or perform a complete wipe. Exports are readable JSON and are not encrypted after export.</p>
        </section>
        <Link className="text-sm text-primary underline" href="/">Back to workspace</Link>
      </article>
    </main>
  )
}
