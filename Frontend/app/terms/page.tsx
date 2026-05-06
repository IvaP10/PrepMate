export default function TermsPage() {
  return (
    <main className="min-h-screen bg-background p-6 text-foreground">
      <article className="mx-auto max-w-3xl space-y-5 leading-7">
        <h1 className="text-3xl font-semibold tracking-tight">Terms of Service</h1>
        <p className="text-muted-foreground">These terms govern use of InterAI interview practice, coaching, technical-round, and payment features.</p>
        <h2 className="text-lg font-semibold">Use Of The Service</h2>
        <p>Use InterAI for lawful interview preparation. Do not attempt to bypass rate limits, anti-cheat controls, code execution limits, authentication, or payment flows.</p>
        <h2 className="text-lg font-semibold">Interview Outputs</h2>
        <p>Questions, scores, reports, and exercises are practice guidance, not hiring guarantees. You remain responsible for how you use the feedback.</p>
        <h2 className="text-lg font-semibold">Technical Mode</h2>
        <p>Technical rounds may block paste, log tab switches, request fullscreen, and run submitted code through the configured Piston execution service.</p>
        <h2 className="text-lg font-semibold">Payments</h2>
        <p>Paid plans and credit purchases are processed through Razorpay. Refunds, cancellations, and access changes follow the plan terms shown at checkout.</p>
      </article>
    </main>
  )
}
