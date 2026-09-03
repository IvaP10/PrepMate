import type { ReactNode } from "react";
import { MotionEnhancer } from "@/components/motion-enhancer";
import { PrepMateLogo } from "@/components/prepmate-logo";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { SiteLink } from "@/components/site-link";

export const dynamic = "force-static";

const appSections = [
  "Resume",
  "Interview Round",
  "Technical Round",
  "Performance",
  "Improve",
];

const practiceSteps = [
  {
    index: "01",
    title: "Bring the real context",
    body: "Use your resume, target role, and job description so practice starts from the interview you are actually preparing for.",
  },
  {
    index: "02",
    title: "Practice the round",
    body: "Rehearse behavioral answers or work through technical rounds in a focused desktop environment built for deliberate practice.",
  },
  {
    index: "03",
    title: "Turn evidence into repetition",
    body: "Review what your answer proved, find recurring patterns in Performance, and open the next focused exercise in Improve.",
  },
];

function ProductChrome({
  active,
  className = "",
  children,
}: {
  active: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={`product-window ${className}`.trim()}>
      <div className="product-titlebar">
        <span className="window-dots" aria-hidden="true"><i /><i /><i /></span>
        <span className="product-title">PrepMate</span>
        <span className="local-status"><i aria-hidden="true" /> On this Mac</span>
      </div>
      <div className="product-layout">
        <aside className="product-sidebar" aria-label="App sections">
          <div className="product-brand"><PrepMateLogo className="product-brand-logo" size={23} decorative /><strong>PrepMate</strong></div>
          <span className="product-nav-label">Prepare</span>
          {appSections.slice(0, 3).map((section) => (
            <span className={`product-nav-item${active === section ? " active" : ""}`} key={section}>{section}</span>
          ))}
          <span className="product-nav-label product-nav-label-spaced">Grow</span>
          {appSections.slice(3).map((section) => (
            <span className={`product-nav-item${active === section ? " active" : ""}`} key={section}>{section}</span>
          ))}
          <span className="product-nav-item product-nav-settings">Settings</span>
        </aside>
        {children}
      </div>
    </div>
  );
}

function PracticePreview() {
  return (
    <div className="practice-surface">
      <div className="practice-toolbar">
        <span className="practice-round">Interview Round</span>
        <span className="practice-timer"><i aria-hidden="true" /> 04:18</span>
      </div>
      <div className="practice-content">
        <span className="question-number">Question 03</span>
        <h2>Tell me about a decision you owned—and what changed because of it.</h2>
        <div className="listening-state"><i aria-hidden="true" /> Listening</div>
        <div className="waveform" aria-hidden="true">
          {[18, 31, 46, 24, 56, 39, 67, 34, 51, 28, 43, 20, 34, 17].map((height, index) => (
            <span key={index} style={{ height }} />
          ))}
        </div>
        <div className="practice-footer">
          <span className="evidence-chip"><i aria-hidden="true">✓</i> Evidence captured privately</span>
          <span className="finish-answer">Finish answer <b aria-hidden="true">→</b></span>
        </div>
      </div>
    </div>
  );
}

export default function Home() {
  return (
    <main className="site-shell">
      <MotionEnhancer />
      <SiteHeader />

      <section className="hero-cinematic" data-motion="hero" aria-labelledby="hero-title">
        <div className="hero-sticky">
          <div className="hero hero-redesign">
            <div className="hero-copy hero-copy-redesign">
              <p className="availability-pill"><span aria-hidden="true" /> Built for macOS</p>
              <h1 id="hero-title">
                <span className="hero-title-line"><span>Practice the interview.</span></span>
                <span className="hero-title-line"><span>Keep the advantage.</span></span>
              </h1>
              <p className="hero-lede">
                PrepMate is a private AI interview practice studio that turns every
                answer into evidence, every session into insight, and every weakness
                into your next focused practice.
              </p>
              <div className="hero-actions">
                <SiteLink className="button button-primary" href="/download">Download for macOS <span aria-hidden="true">↓</span></SiteLink>
              </div>
              <p className="hero-note">macOS 13+ · Apple Silicon &amp; Intel · No account required</p>
            </div>
            <div className="hero-product-stage" aria-label="PrepMate desktop app preview">
              <div className="stage-orbit stage-orbit-one" aria-hidden="true" />
              <div className="stage-orbit stage-orbit-two" aria-hidden="true" />
              <ProductChrome active="Interview Round" className="product-window-hero">
                <PracticePreview />
              </ProductChrome>
              <div className="stage-caption"><span aria-hidden="true">⌁</span> Your context stays on your Mac</div>
            </div>
          </div>
        </div>
      </section>

      <div className="principle-rail" aria-label="Product principles">
        <span>Desktop, not a web app</span><i aria-hidden="true" />
        <span>Private by default</span><i aria-hidden="true" />
        <span>Your provider, your key</span><i aria-hidden="true" />
        <span>Made only for macOS</span>
      </div>

      <section className="landing-section flow-section" id="how-it-works">
        <div className="section-heading">
          <p className="section-kicker">One deliberate practice loop</p>
          <h2>From first answer<br />to focused repetition.</h2>
          <p>
            PrepMate connects the parts most interview tools leave scattered:
            your context, the live round, the evidence, and exactly what to
            practice next.
          </p>
        </div>
        <div className="flow-steps">
          {practiceSteps.map((step) => (
            <article className="flow-step" key={step.index}>
              <span>{step.index}</span>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="product-storyboard" id="product" data-motion="storyboard" aria-label="PrepMate product story">
        <div className="storyboard-sticky">
          <div className="product-intro storyboard-intro">
            <p className="section-kicker">The app is the experience</p>
            <h2>Everything you need.<br /><span>Nothing competing for attention.</span></h2>
            <span className="storyboard-scroll-cue">Scroll to explore <i aria-hidden="true">↓</i></span>
          </div>

          <div className="storyboard-scenes">
            <article className="story-scene story-scene-practice" data-story-scene="0">
              <div className="story-copy">
                <span className="story-number">01 / Practice</span>
                <h3>A room built for the real question.</h3>
                <p>
                  Start with your resume and target role, then practice by voice or
                  text. The interface gets out of the way so you can listen, think,
                  and answer with intent.
                </p>
                <ul className="story-points">
                  <li>Behavioral and technical rounds</li>
                  <li>Role-aware questions from your context</li>
                  <li>Optional camera, microphone, and screen coaching</li>
                </ul>
              </div>
              <div className="story-visual story-visual-practice">
                <div className="story-window-depth">
                  <ProductChrome active="Interview Round" className="product-window-story">
                    <PracticePreview />
                  </ProductChrome>
                </div>
              </div>
            </article>

            <article className="story-scene story-scene-review" data-story-scene="1">
              <div className="story-visual story-visual-report">
                <div className="story-window-depth">
                  <ProductChrome active="Performance" className="product-window-story">
                    <div className="report-surface">
                      <div className="report-header">
                        <div><span className="app-kicker">Interview report</span><h4>Your answer, grounded in evidence.</h4></div>
                        <span className="report-badge">Ready to review</span>
                      </div>
                      <div className="report-body">
                        <aside className="report-outline">
                          <span className="active">Summary</span><span>Evidence</span><span>Patterns</span><span>Next steps</span>
                        </aside>
                        <div className="report-detail">
                          <span className="detail-label">What landed</span>
                          <p className="report-quote">“You made the decision clear and connected it to a measurable result.”</p>
                          <div className="evidence-row"><span>Captured strength</span><strong>Ownership with concrete proof</strong></div>
                          <div className="evidence-row"><span>Sharpen next</span><strong>State the trade-off earlier</strong></div>
                        </div>
                      </div>
                    </div>
                  </ProductChrome>
                </div>
              </div>
              <div className="story-copy">
                <span className="story-number">02 / Review</span>
                <h3>Feedback you can trace back to the answer.</h3>
                <p>
                  PrepMate keeps the useful evidence from each session. Reports show
                  what worked, what weakened the answer, and the exact next action—so
                  feedback stays specific instead of turning into a generic score.
                </p>
                <ul className="story-points">
                  <li>Evidence-backed findings</li>
                  <li>Question-by-question review</li>
                  <li>Clear strengths, mistakes, and next actions</li>
                </ul>
              </div>
            </article>

            <article className="story-scene story-scene-improve" data-story-scene="2">
              <div className="story-copy">
                <span className="story-number">03 / Improve</span>
                <h3>Practice the pattern, not just another question.</h3>
                <p>
                  Performance connects evidence across sessions. Improve then turns
                  the recurring pattern into a compact exercise with a clear pass
                  condition and a reason to repeat it.
                </p>
                <ul className="story-points">
                  <li>Patterns across your practice history</li>
                  <li>Focused, repeatable exercises</li>
                  <li>Progress stored locally on your Mac</li>
                </ul>
              </div>
              <div className="story-visual story-visual-improve">
                <div className="story-window-depth">
                  <ProductChrome active="Improve" className="product-window-story">
                    <div className="improve-surface">
                      <div className="improve-heading"><span className="app-kicker">Focused practice</span><h4>Lead with the decision.</h4><p>Build a concise answer that shows ownership before context.</p></div>
                      <div className="exercise-panel">
                        <span className="exercise-label">What good looks like</span>
                        <strong>Direct point. Decision. Proof. Result.</strong>
                        <div className="exercise-checks">
                          <span><i>✓</i> Start with a direct answer</span>
                          <span><i>✓</i> Name the decision you owned</span>
                          <span><i>✓</i> End with evidence or a result</span>
                        </div>
                        <span className="exercise-action">Start practice <b aria-hidden="true">→</b></span>
                      </div>
                    </div>
                  </ProductChrome>
                </div>
              </div>
            </article>
          </div>

          <div className="storyboard-progress" aria-hidden="true">
            <span>Practice</span><span>Review</span><span>Improve</span>
          </div>
        </div>
      </section>

      <section className="privacy-section" id="privacy" data-motion="privacy">
        <div className="privacy-copy">
          <p className="section-kicker">Local first, by design</p>
          <h2>Your practice belongs on your computer.</h2>
          <p>
            Resumes, answers, reports, Performance, and Improve history stay in
            PrepMate&apos;s local workspace. There is no PrepMate account and no
            PrepMate-hosted application backend.
          </p>
                <SiteLink className="inline-link" href="/privacy">Read the privacy boundary <span aria-hidden="true">↗</span></SiteLink>
        </div>
        <div className="privacy-diagram" aria-label="PrepMate local-first data flow">
          <div className="privacy-node privacy-device">
            <span className="node-kicker">On your Mac</span>
            <strong>PrepMate workspace</strong>
            <div><span>Resume context</span><span>Practice history</span><span>Reports &amp; progress</span></div>
          </div>
          <div className="privacy-route">
            <span>Only when you choose</span>
            <i aria-hidden="true" />
          </div>
          <div className="privacy-node privacy-provider">
            <span className="node-kicker">Direct connection</span>
            <strong>Your AI provider</strong>
            <p>Configured explicitly in Settings</p>
          </div>
        </div>
        <p className="provider-note">Settings includes configuration for OpenAI, Anthropic, Google Gemini, and OpenAI-compatible endpoints—including local endpoints.</p>
      </section>

      <section className="desktop-statement landing-section" data-motion="statement">
        <div className="desktop-statement-content">
          <p className="section-kicker">Deliberately desktop</p>
          <h2>Not another tab.<br /><span>A place to rehearse.</span></h2>
          <p>
            PrepMate is a dedicated macOS app, with local history, OS-keychain
            credentials, and a focused workspace that is there when you need it
            and quiet when you do not.
          </p>
        </div>
      </section>

      <section className="final-cta">
        <div>
          <p className="section-kicker">Available for macOS only</p>
          <h2>Your next interview deserves a rehearsal.</h2>
          <p>Choose the build for your Apple Silicon or Intel Mac on the download page.</p>
        </div>
        <div className="final-cta-actions">
              <SiteLink className="button button-contrast" href="/download">Download for macOS <span aria-hidden="true">↓</span></SiteLink>
          <span>No web or Windows version at this time.</span>
        </div>
      </section>

      <SiteFooter />
    </main>
  );
}
