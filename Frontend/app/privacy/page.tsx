import { LegalPageShell, type LegalSection } from "@/components/legal-page-shell"
import { PublicContactDetails } from "@/components/public-contact-details"

const sections: LegalSection[] = [
  { id: "overview", title: "Overview" },
  { id: "data-we-collect", title: "Data We Collect" },
  { id: "how-we-use-data", title: "How We Use Data" },
  { id: "ai-processing", title: "AI And External Processing" },
  { id: "voice-video", title: "Voice And Video" },
  { id: "technical-data", title: "Technical Data" },
  { id: "cookies", title: "Cookies" },
  { id: "sharing", title: "Sharing" },
  { id: "retention", title: "Retention" },
  { id: "controls", title: "Your Controls" },
  { id: "security", title: "Security" },
  { id: "contact", title: "Contact" },
]

export default function PrivacyPage() {
  return (
    <LegalPageShell
      eyebrow="Legal"
      title="Privacy Policy"
      description="This policy explains how InterAI handles account, resume, interview, technical-round, payment, telemetry, and support information — including when that information is sent to external service providers."
      updated="June 3, 2026"
      sections={sections}
    >
      <section id="overview">
        <h2>1. Overview</h2>
        <p>
          InterAI processes resume, interview, code, voice, coaching, usage, and billing data to
          provide interview practice and analytics. This Privacy Policy applies to InterAI websites,
          dashboards, interview rooms, technical workspaces, reports, settings, support flows, and
          related services.
        </p>
        <p>
          <strong>Important:</strong> InterAI relies on external third-party providers for core
          features such as AI inference, speech transcription, authentication, payments, code
          execution, email, hosting, and observability. By creating an account or using InterAI,
          you understand that certain information you provide may be transmitted to those providers
          to operate the service. See sections 4 and 8 for details on external AI processing,
          what may be sent, and the limits of our anonymization efforts.
        </p>
      </section>

      <section id="data-we-collect">
        <h2>2. Data we collect</h2>
        <p>Depending on the features you use, we may collect and store:</p>
        <ul>
          <li>account details, such as name, email, authentication provider, verification status, and session metadata;</li>
          <li>resume and profile data, including parsed resume fields, skills, experience, education, projects, job profiles, and target roles;</li>
          <li>interview data, including questions, answers, transcripts, scores, feedback, reports, durations, and completion status;</li>
          <li>technical-round data, including prompts, code excerpts, code hashes, language, stdout, stderr, runtime, test results, whiteboard data, and anti-cheat events;</li>
          <li>learning data, such as generated exercises, attempts, coaching recommendations, and performance analytics;</li>
          <li>payment metadata, such as plan, amount, currency, transaction status, provider order IDs, invoices, and Razorpay verification metadata;</li>
          <li>support and feedback messages, bug reports, ratings, page URLs, and optional interview IDs;</li>
          <li>device, browser, log, security, latency, model, provider, and error metadata for operation and abuse prevention.</li>
        </ul>
      </section>

      <section id="how-we-use-data">
        <h2>3. How we use data</h2>
        <p>We use data to:</p>
        <ul>
          <li>create and secure accounts, sessions, verification flows, and Google Sign-In flows;</li>
          <li>parse resumes, build user profiles, generate interview questions, and tailor difficulty — including by sending content to external AI providers as described in section 4;</li>
          <li>transcribe speech, run mock interviews, generate reports, and produce coaching exercises;</li>
          <li>prepare technical rounds, execute code, validate test cases, and provide technical feedback;</li>
          <li>enforce plan limits, credits, payment status, rate limits, security controls, and anti-cheat rules;</li>
          <li>process purchases, verify Razorpay payments, produce billing history, and support refund review;</li>
          <li>debug errors, measure reliability, improve product quality, and respond to support requests;</li>
          <li>comply with law, prevent fraud or abuse, protect users, and protect InterAI.</li>
        </ul>
      </section>

      <section id="ai-processing">
        <h2>4. External AI processing and data sent to third parties</h2>
        <p>
          InterAI uses external AI and infrastructure providers to deliver resume parsing, question
          generation, live interview responses, coaching, reports, speech-to-text, text-to-speech,
          code execution, authentication, payments, email, hosting, analytics, and error monitoring.
          When you use these features, content derived from your account, resume, interviews, and
          technical sessions may leave InterAI&apos;s systems and be processed by third parties under
          their own terms and privacy policies.
        </p>

        <h3>What we try to remove before external AI requests</h3>
        <p>
          Before sending text to external language-model providers, InterAI applies automated PII
          minimization. We attempt to remove or replace direct identifiers such as email addresses,
          phone numbers, social profile URLs, government ID numbers, payment card numbers, dates of
          birth, and known profile names with placeholders.
        </p>

        <h3>What may still be sent externally</h3>
        <p>
          Our redaction pipeline is best-effort and cannot guarantee complete anonymization. Some
          personal or identifying information may still reach external providers, including when it
          appears in formats our systems do not detect, is embedded in free text, or is necessary for
          the feature to work. Examples include:
        </p>
        <ul>
          <li>names, nicknames, or initials that are not matched by our redaction rules;</li>
          <li>employer names, school names, project titles, or other context that may identify you;</li>
          <li>addresses, locations, or uncommon contact formats missed by automated detection;</li>
          <li>resume sections, skills, experience descriptions, and project details needed for personalization;</li>
          <li>interview questions, spoken answers, transcripts, scores, feedback, and coaching text;</li>
          <li>voice audio sent to OpenAI speech-to-text services;</li>
          <li>code, compiler output, test results, and technical-round telemetry sent to execution or analysis services;</li>
          <li>job descriptions, target roles, and job-profile context you provide;</li>
          <li>support messages, bug reports, and error metadata sent to email, logging, or observability tools.</li>
        </ul>

        <h3>Resume uploads specifically</h3>
        <p>
          Resume files are parsed on InterAI infrastructure where possible. Structured extraction may
          then call an external language model using redacted resume text. Contact details extracted
          during upload are stored in your InterAI account for profile display and are not
          intentionally re-sent for routine interview generation, but other resume content may still
          be transmitted to external models as described above.
        </p>

        <h3>Providers and international processing</h3>
        <p>
          Depending on configuration, external providers may include OpenAI, Google Sign-In,
          Razorpay, the private isolated code sandbox, cloud hosting providers, database and
          cache infrastructure, email providers, Sentry, PostHog, Langfuse-compatible observability
          tools, and other configured model gateways or subprocessors. These providers may process
          data in countries other than your own. Their retention, security, and use of submitted
          content are governed by their own policies, not this one.
        </p>

        <h3>Your responsibility</h3>
        <p>
          Do not upload or enter information through InterAI that you are not authorized to share or
          that you would not want processed by an external provider. If you need assurance that
          specific data will not leave InterAI, do not submit it. For a current list of categories
          and providers, also see section 8 below.
        </p>
      </section>

      <section id="voice-video">
        <h2>5. Voice, camera, and body-language features</h2>
        <p>
          Speech audio may be sent to OpenAI speech-to-text services for
          transcription. Transcripts and derived text may then be sent to external language models
          for interview flow, scoring, coaching, and reporting. Voice recordings themselves are
          processed by the configured transcription provider under that provider&apos;s policies.
          Improve voice exercises may capture transcript-only input. Mock interview rooms may use
          microphone, camera, fullscreen, and screen-sharing permissions depending on the mode and
          browser capabilities.
        </p>
        <p>
          Body-language analysis is designed to run in the browser with MediaPipe-style processing.
          InterAI stores derived metrics where needed for reports and analysis. The V1 architecture
          avoids sending raw video frames to the backend for body-language analysis.
        </p>
      </section>

      <section id="technical-data">
        <h2>6. Technical rounds and integrity data</h2>
        <p>
          Technical rounds may log code runs, code hashes, code excerpts, compiler output, runtime
          output, hidden-validation metadata, whiteboard data, and event telemetry. Integrity events
          may include paste attempts, large code jumps, tab switches, fullscreen exits, screen-share
          stops, permission failures, blocked drops, suspicious fast submissions, and related
          payloads.
        </p>
      </section>

      <section id="cookies">
        <h2>7. Cookies and similar technologies</h2>
        <p>
          InterAI uses cookies and similar browser storage for authentication, CSRF protection,
          session continuity, theme preferences, app tab preferences, security, and product
          operation. These technologies help keep you signed in, preserve your settings, protect
          against cross-site request forgery, and route authenticated requests safely.
        </p>
        <p>
          We may also use analytics or observability tools to understand reliability, usage, and
          errors. If optional marketing or analytics controls are added, you will be able to manage
          supported choices through the product or browser settings where available.
        </p>
      </section>

      <section id="sharing">
        <h2>8. When we share data with third parties</h2>
        <p>
          We share data with third parties as needed to operate, secure, bill, support, and improve
          InterAI, comply with law, process payments, provide authentication, run AI inference,
          transcribe speech, execute code, send email, host infrastructure, analyze reliability, or
          respond to valid legal requests. Sharing is not limited to anonymized data; some personal
          or identifying information may be included when required for the service to function or
          when our automated redaction does not remove it.
        </p>

        <h3>Categories of recipients</h3>
        <ul>
          <li>
            <strong>AI and model providers</strong> — OpenAI receives prompts, resume context,
            interview transcripts, coaching inputs, and related text needed to generate questions,
            responses, reports, and exercises.
          </li>
          <li>
            <strong>Speech providers</strong> — OpenAI receives audio for
            transcription during interviews and voice exercises.
          </li>
          <li>
            <strong>Authentication and identity</strong> — Google Sign-In and related identity
            services receive authentication tokens and account metadata you choose to use.
          </li>
          <li>
            <strong>Payments</strong> — Razorpay receives billing details, order metadata, and
            verification data. Payment credentials remain with the payment provider and are not
            stored by InterAI.
          </li>
          <li>
            <strong>Code execution</strong> — our private isolated sandbox receives source
            code, language metadata, stdin, and runtime output for technical rounds.
          </li>
          <li>
            <strong>Infrastructure and operations</strong> — cloud hosting, databases, caches, email
            delivery, support tooling, and observability services such as Sentry, PostHog, and
            Langfuse-compatible telemetry may receive logs, error reports, usage metadata, and limited
            content snippets needed for debugging or analytics.
          </li>
        </ul>

        <p>
          Each third party processes data according to its own terms, privacy policy, retention
          schedule, and security practices. InterAI does not control how external providers use,
          store, train on, or retain submitted content after it is transmitted. Where available, we
          configure providers for API use intended for service delivery, but you should review their
          policies directly if this matters for your use case.
        </p>
      </section>

      <section id="retention">
        <h2>9. Retention</h2>
        <p>
          We retain data for as long as needed to provide the service, maintain records, analyze
          performance, prevent abuse, resolve disputes, satisfy legal obligations, and support user
          controls. Account deletion removes the account and associated practice data, interviews,
          scores, resume, and job profiles according to product behavior and applicable legal
          requirements.
        </p>
      </section>

      <section id="controls">
        <h2>10. Your controls</h2>
        <p>
          In settings, you can export account data, update account information, change notification
          preferences, and delete your account. Some retained logs, payment records, anti-abuse
          records, security records, or legal records may be kept where necessary or required by
          law.
        </p>
      </section>

      <section id="security">
        <h2>11. Security and limits of anonymization</h2>
        <p>
          InterAI uses safeguards such as authentication cookies, CSRF checks, password hashing,
          login rate limits, transport security in production, field encryption where configured,
          automated PII redaction before external AI requests, provider credential controls, logging
          redaction, and access controls.
        </p>
        <p>
          No internet service is completely secure, and no automated redaction system is perfect.
          Identifiers or other sensitive details may still be transmitted to external providers if
          our pipeline misses them, if they are embedded in professional context needed for the
          feature, or if you speak or type them during an interview. You should avoid uploading or
          entering content that you are not allowed to share or that you are not comfortable having
          processed by third-party services.
        </p>
      </section>

      <section id="contact">
        <h2>12. Contact</h2>
        <p><PublicContactDetails /></p>
      </section>
    </LegalPageShell>
  )
}
