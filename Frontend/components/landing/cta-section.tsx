"use client"

import { ArrowRight } from "lucide-react"

interface CtaSectionProps {
  onGetStarted: () => void
}

export function CtaSection({ onGetStarted }: CtaSectionProps) {
  return (
    <section className="landing-chapter-gap relative px-6 py-12 md:py-14">
      <div className="mx-auto max-w-5xl rounded-2xl border border-primary/20 bg-primary/[0.045] px-6 py-10 text-center sm:px-10 sm:py-12">
        <h2 className="mx-auto max-w-2xl text-balance text-3xl font-semibold tracking-[-0.035em] text-foreground sm:text-4xl">Prepare. Get evidence. Practice the gaps.</h2>
        <p className="mx-auto mt-4 max-w-xl text-base leading-7 text-muted-foreground">Start with your resume and turn the next answer into a stronger one.</p>
        <button onClick={onGetStarted} className="mt-7 inline-flex h-12 items-center gap-2 rounded-lg bg-primary px-6 text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/20 transition hover:brightness-110">Create your account <ArrowRight className="h-4 w-4" /></button>
      </div>
    </section>
  )
}
