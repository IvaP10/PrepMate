import { LegalPageShell, type LegalSection } from "@/components/legal-page-shell"

const sections: LegalSection[] = [
  { id: "mission", title: "Mission" },
  { id: "how-it-works", title: "How It Works" },
  { id: "responsible-use", title: "Responsible Use" },
  { id: "contact", title: "Contact" },
]

export default function AboutPage() {
  return (
    <LegalPageShell
      eyebrow="Company"
      title="About InterAI"
      description="InterAI is an AI-driven interview-practice platform that helps candidates rehearse realistic interviews, strengthen technical communication, and turn feedback into focused preparation."
      sections={sections}
    >
      <section id="mission">
        <h2>Our mission</h2>
        <p>
          InterAI exists to make serious interview preparation more accessible, structured, and
          measurable. The product uses your resume, target role, and practice history to create
          realistic mock interviews, technical rounds, feedback reports, and focused exercises that
          help you improve before high-stakes conversations.
        </p>
      </section>

      <section id="how-it-works">
        <h2>How the product works</h2>
        <p>
          You can upload or maintain a professional profile, choose a company-style preparation
          track, run mock interviews or technical rounds, and review reports that summarize strengths,
          weak answers, technical mistakes, and next practice steps. InterAI combines deterministic
          parsing, browser-side media processing where appropriate, speech transcription, code
          execution, AI-generated questions, and evidence-based scoring.
        </p>
      </section>

      <section id="responsible-use">
        <h2>Responsible preparation</h2>
        <p>
          InterAI is a preparation tool, not a shortcut for real assessments. The goal is to help you
          practice honestly, understand your gaps, and build clearer answers. Technical-round
          integrity features and monitoring signals are designed to keep practice realistic and to
          protect the value of the feedback you receive.
        </p>
      </section>

      <section id="contact">
        <h2>Contact</h2>
        <p>
          For product support, contact [support email]. For privacy questions, contact [privacy
          email]. For legal notices, contact [legal notices email].
        </p>
      </section>
    </LegalPageShell>
  )
}
