"use client"
import { useEffect, useRef } from "react"

interface PremiumBackgroundProps {
  theme?: "light" | "dark"
}

const QUESTIONS = [
  "Tell me about yourself",
  "Why this company?",
  "Greatest strength?",
  "Where do you see yourself in 5 years?",
  "Describe a challenge you overcame",
  "Why should we hire you?",
  "What motivates you?",
  "Team or solo work?",
  "Biggest weakness?",
  "Most proud achievement?",
  "How do you handle pressure?",
  "Leadership example?",
  "Salary expectations?",
  "Any questions for us?",
  "Problem-solving approach?",
  "Walk me through your resume",
  "How do you handle conflicts at work?",
  "Tell me about a time you failed",
  "What makes you unique?",
  "Describe your ideal work environment",
  "How do you prioritize tasks?",
  "What are your career goals?",
  "How do you stay updated in your field?",
  "Describe a time you went above and beyond",
  "How would your manager describe you?",
  "What is your management style?",
  "Tell me about a difficult decision you made",
  "How do you handle feedback?",
  "What is your greatest accomplishment?",
  "Why are you leaving your current role?",
  "How do you approach learning new skills?",
  "Describe your communication style",
  "What do you know about our industry?",
  "How do you deal with ambiguity?",
  "Tell me about a successful project",
  "What are you passionate about?",
  "How do you build relationships at work?",
  "Describe a time you showed initiative",
  "What would you do in the first 90 days?",
  "How do you measure success?",
]

const ICONS = ["✦", "◈", "⬡", "◇", "○"]

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number, r: number,
) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + w - r, y)
  ctx.quadraticCurveTo(x + w, y, x + w, y + r)
  ctx.lineTo(x + w, y + h - r)
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
  ctx.lineTo(x + r, y + h)
  ctx.quadraticCurveTo(x, y + h, x, y + h - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
}

// ── Entities stored outside the effect so they survive theme changes ──

interface CardEntity {
  text: string; w: number; h: number
  x: number; y: number; vx: number; vy: number
  alpha: number; targetAlpha: number; fadeIn: boolean
}

interface IconEntity {
  icon: string; x: number; y: number
  vx: number; vy: number; alpha: number; size: number
}

function createCard(W: number, H: number, init: boolean, existing?: CardEntity[]): CardEntity {
  // Pick a question not already shown by any existing card
  const usedTexts = new Set(existing?.map(c => c.text) ?? [])
  let text: string
  const available = QUESTIONS.filter(q => !usedTexts.has(q))
  text = available.length > 0
    ? available[Math.floor(Math.random() * available.length)]
    : QUESTIONS[Math.floor(Math.random() * QUESTIONS.length)]
  const w = text.length * 8.5 + 32
  const h = 38
  let x: number, y: number
  let attempts = 0

  // Place with collision avoidance
  do {
    x = init ? Math.random() * W : -w - 20
    y = init ? (Math.random() * (H - 60)) + 30 : (Math.random() * (H - 60)) + 30
    attempts++
  } while (
    init && attempts < 40 && existing &&
    existing.some(c => {
      const overlapX = x < c.x + c.w + 10 && x + w + 10 > c.x
      const overlapY = y < c.y + c.h + 10 && y + h + 10 > c.y
      return overlapX && overlapY
    })
  )

  return {
    text, w, h, x, y,
    vx: 0.18 + Math.random() * 0.22,
    vy: (Math.random() - 0.5) * 0.12,
    alpha: init ? Math.random() * 0.25 + 0.06 : 0,
    targetAlpha: 0.1 + Math.random() * 0.2,
    fadeIn: !init,
  }
}

function createIcon(W: number, H: number): IconEntity {
  return {
    icon: ICONS[Math.floor(Math.random() * ICONS.length)],
    x: Math.random() * W,
    y: Math.random() * H,
    vx: (Math.random() - 0.5) * 0.12,
    vy: (Math.random() - 0.5) * 0.12,
    alpha: 0.15 + Math.random() * 0.2,
    size: 10 + Math.random() * 10,
  }
}

export function PremiumBackground({ theme = "dark" }: PremiumBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animRef = useRef<number>(0)
  const themeRef = useRef(theme)
  const entitiesRef = useRef<{ cards: CardEntity[]; icons: IconEntity[] } | null>(null)

  // Keep theme ref in sync — NO effect dependency on theme
  themeRef.current = theme

  // Single effect that runs once — reads theme from ref
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    let W = window.innerWidth
    let H = window.innerHeight
    canvas.width = W
    canvas.height = H

    const resize = () => {
      W = window.innerWidth
      H = window.innerHeight
      canvas.width = W
      canvas.height = H
    }
    window.addEventListener("resize", resize)

    // ── Create entities only once ──
    if (!entitiesRef.current) {
      const cards: CardEntity[] = []
      for (let i = 0; i < 18; i++) {
        cards.push(createCard(W, H, true, cards))
      }
      const icons = Array.from({ length: 8 }, () => createIcon(W, H))
      entitiesRef.current = { cards, icons }
    }

    const { cards, icons } = entitiesRef.current
    const CONNECT_DIST = 180

    // ── Helper: get theme-aware colors (read from ref each frame) ──
    function getColors() {
      const dark = themeRef.current === "dark"
      return {
        dark,
        fg: dark ? "255,255,255" : "30,58,138",
        cardFill: dark ? "rgba(255,255,255,0.06)" : "rgba(30,58,138,0.14)",
        cardStroke: dark ? "rgba(255,255,255,0.4)" : "rgba(30,58,138,0.65)",
        cardText: dark ? "rgba(255,255,255,0.75)" : "rgba(30,58,138,0.85)",
        checkColor: dark ? "#4ade80" : "#16a34a",
        iconFill: dark ? "#ffffff" : "#1e3a8a",
        bubbleStroke: dark ? "rgba(255,255,255,0.4)" : "rgba(30,58,138,0.5)",
        bubbleFill: dark ? "rgba(255,255,255,0.05)" : "rgba(30,58,138,0.1)",
      }
    }

    // ── Card update with soft repulsion ──
    function updateCards() {
      for (let i = 0; i < cards.length; i++) {
        const c = cards[i]
        if (c.fadeIn && c.alpha < c.targetAlpha) c.alpha += 0.003
        c.x += c.vx
        c.y += c.vy

        // Soft repulsion from other cards
        for (let j = 0; j < cards.length; j++) {
          if (i === j) continue
          const other = cards[j]
          const overlapX = c.x < other.x + other.w + 6 && c.x + c.w + 6 > other.x
          const overlapY = c.y < other.y + other.h + 6 && c.y + c.h + 6 > other.y
          if (overlapX && overlapY) {
            // Push apart vertically
            const myCenter = c.y + c.h / 2
            const otherCenter = other.y + other.h / 2
            if (myCenter < otherCenter) {
              c.vy -= 0.02
            } else {
              c.vy += 0.02
            }
          }
        }

        // Clamp vy to prevent runaway
        c.vy = Math.max(-0.3, Math.min(0.3, c.vy))

        // Soft vertical bounds
        if (c.y < 10) c.vy += 0.01
        if (c.y + c.h > H - 10) c.vy -= 0.01

        if (c.x > W + 60) {
          const newCard = createCard(W, H, false, cards)
          cards[i] = newCard
        }
      }
    }

    // ── Icon update ──
    function updateIcons() {
      icons.forEach((ic) => {
        ic.x += ic.vx
        ic.y += ic.vy
        if (ic.x < -20) ic.x = W + 20
        if (ic.x > W + 20) ic.x = -20
        if (ic.y < -20) ic.y = H + 20
        if (ic.y > H + 20) ic.y = -20
      })
    }

    // ── Draw connections ──
    function drawConnections(colors: ReturnType<typeof getColors>) {
      const nodes = [
        ...cards.map((c) => ({ x: c.x + c.w / 2, y: c.y + c.h / 2, alpha: c.alpha })),
        ...icons.map((ic) => ({ x: ic.x, y: ic.y, alpha: ic.alpha })),
      ]
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j]
          const dx = a.x - b.x, dy = a.y - b.y
          const dist = Math.sqrt(dx * dx + dy * dy)
          if (dist < CONNECT_DIST) {
            const strength = (1 - dist / CONNECT_DIST) * Math.min(a.alpha, b.alpha) * 0.8
            ctx!.beginPath()
            ctx!.moveTo(a.x, a.y)
            ctx!.lineTo(b.x, b.y)
            ctx!.strokeStyle = `rgba(${colors.fg},${strength})`
            ctx!.lineWidth = 0.4
            ctx!.stroke()
          }
        }
      }
    }

    // ── Draw cards ──
    function drawCards(colors: ReturnType<typeof getColors>) {
      cards.forEach((c) => {
        ctx!.save()
        ctx!.globalAlpha = c.alpha
        ctx!.strokeStyle = colors.cardStroke
        ctx!.lineWidth = 0.5
        ctx!.fillStyle = colors.cardFill
        roundRect(ctx!, c.x, c.y, c.w, c.h, 6)
        ctx!.fill()
        ctx!.stroke()
        ctx!.fillStyle = colors.cardText
        ctx!.font = "13px system-ui, sans-serif"
        ctx!.textBaseline = "middle"
        ctx!.fillText(c.text, c.x + 12, c.y + c.h / 2)
        ctx!.restore()
      })
    }

    // ── Draw icons ──
    function drawIcons(colors: ReturnType<typeof getColors>) {
      icons.forEach((ic) => {
        ctx!.save()
        ctx!.globalAlpha = ic.alpha
        ctx!.fillStyle = colors.iconFill
        ctx!.font = `${ic.size}px system-ui`
        ctx!.textBaseline = "middle"
        ctx!.textAlign = "center"
        ctx!.fillText(ic.icon, ic.x, ic.y)
        ctx!.restore()
      })
    }

    // ── Draw checkmarks ──
    function drawCheckmarks(colors: ReturnType<typeof getColors>) {
      const positions = [
        { x: W * 0.08, y: H * 0.18 },
        { x: W * 0.88, y: H * 0.25 },
        { x: W * 0.12, y: H * 0.78 },
        { x: W * 0.85, y: H * 0.72 },
      ]
      const t = Date.now() / 1000
      positions.forEach((p, i) => {
        const pulse = colors.dark ? 0.04 + 0.02 * Math.sin(t * 0.8 + i * 1.5) : 0.2 + 0.1 * Math.sin(t * 0.8 + i * 1.5)
        ctx!.save()
        ctx!.globalAlpha = pulse
        ctx!.strokeStyle = colors.checkColor
        ctx!.lineWidth = 1.5
        ctx!.lineCap = "round"
        ctx!.lineJoin = "round"
        const s = 14
        ctx!.beginPath()
        ctx!.moveTo(p.x, p.y + s * 0.45)
        ctx!.lineTo(p.x + s * 0.35, p.y + s * 0.75)
        ctx!.lineTo(p.x + s * 0.85, p.y + s * 0.1)
        ctx!.stroke()
        ctx!.restore()
      })
    }

    // ── Draw speech bubbles ──
    function drawSpeechBubbles(colors: ReturnType<typeof getColors>) {
      const bs = [
        { x: W * 0.05, y: H * 0.42, w: 60, h: 28 },
        { x: W * 0.88, y: H * 0.5, w: 52, h: 26 },
      ]
      const t = Date.now() / 1000
      bs.forEach((b, i) => {
        const a = colors.dark ? 0.05 + 0.03 * Math.sin(t * 0.6 + i * 2.1) : 0.2 + 0.08 * Math.sin(t * 0.6 + i * 2.1)
        ctx!.save()
        ctx!.globalAlpha = a
        ctx!.strokeStyle = colors.bubbleStroke
        ctx!.lineWidth = 0.8
        ctx!.fillStyle = colors.bubbleFill
        roundRect(ctx!, b.x, b.y, b.w, b.h, 8)
        ctx!.fill()
        ctx!.stroke()
        // tail
        ctx!.beginPath()
        ctx!.moveTo(b.x + 14, b.y + b.h)
        ctx!.lineTo(b.x + 8, b.y + b.h + 8)
        ctx!.lineTo(b.x + 22, b.y + b.h)
        ctx!.closePath()
        ctx!.fill()
        ctx!.stroke()
        ctx!.restore()
      })
    }

    // ── Animation loop ──
    function animate() {
      ctx!.clearRect(0, 0, W, H)
      const colors = getColors()

      updateCards()
      updateIcons()
      drawConnections(colors)
      drawCards(colors)
      drawIcons(colors)
      drawCheckmarks(colors)
      drawSpeechBubbles(colors)

      animRef.current = requestAnimationFrame(animate)
    }

    animate()

    return () => {
      cancelAnimationFrame(animRef.current)
      window.removeEventListener("resize", resize)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // Run once — theme read from ref

  const isDark = theme === "dark"

  return (
    <>
      {/* Base background color */}
      <div
        className="pointer-events-none fixed inset-0 -z-[11] transition-colors duration-500"
        aria-hidden="true"
        style={{ background: isDark ? "#0F0F0F" : "#FAFAF8" }}
      />
      {/* Animation canvas */}
      <canvas
        ref={canvasRef}
        className="pointer-events-none fixed inset-0 -z-10"
        aria-hidden="true"
      />
      {/* Subtle noise texture */}
      <div
        className="pointer-events-none fixed inset-0 -z-[9] opacity-[0.015]"
        aria-hidden="true"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
          backgroundRepeat: "repeat",
          backgroundSize: "128px 128px",
        }}
      />
    </>
  )
}
