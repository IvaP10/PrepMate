export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-background p-6 text-foreground">
      <article className="mx-auto max-w-3xl space-y-5 leading-7">
        <h1 className="text-3xl font-semibold tracking-tight">Privacy Policy</h1>
        <p className="text-muted-foreground">InterAI processes resume, interview, code, voice, and coaching data to provide interview practice and analytics.</p>
        <h2 className="text-lg font-semibold">Data We Use</h2>
        <p>We store account details, parsed resume fields, job profiles, interview questions, transcripts, scores, generated coaching exercises, technical-round submissions, payment transaction metadata, and support messages.</p>
        <h2 className="text-lg font-semibold">Voice And Video</h2>
        <p>Speech is sent to Groq Whisper for transcription. Body-language analysis runs in the browser with MediaPipe; video frames are not sent to the backend.</p>
        <h2 className="text-lg font-semibold">Telemetry</h2>
        <p>We log provider, model, latency, error, and usage metadata for observability and future quality improvements. We do not log raw payment card data.</p>
        <h2 className="text-lg font-semibold">Your Controls</h2>
        <p>You can export account data, delete session history, reset your profile, or delete your account from settings.</p>
      </article>
    </main>
  )
}
