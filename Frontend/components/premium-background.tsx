"use client"
import { useEffect, useRef } from "react"

interface PremiumBackgroundProps {
  theme?: "light" | "dark"
  mode?: "base" | "comets"
}

interface Star {
  x: number        // static horizontal coordinate
  y: number        // static vertical coordinate
  size: number     // star radius
  alpha: number    // base brightness
  twinkleSpeed: number
  phase: number    // unique twinkling offset
  glow: boolean    // slightly larger glowing stars
}

interface Comet {
  x: number
  y: number
  vx: number
  vy: number
  length: number
  alpha: number
  speed: number
  width: number
}

function createComet(W: number, H: number): Comet {
  const startFromTop = Math.random() > 0.4
  let x = 0, y = 0
  if (startFromTop) {
    x = Math.random() * (W * 0.8)
    y = -30
  } else {
    x = -30
    y = Math.random() * (H * 0.4)
  }
  const angle = (20 + Math.random() * 25) * Math.PI / 180 // travel diagonal down-right
  const speed = 6 + Math.random() * 6 // 25% less speed (fades from 8-16px to 6-12px)
  return {
    x,
    y,
    vx: Math.cos(angle) * speed,
    vy: Math.sin(angle) * speed,
    length: 20 + Math.random() * 110, // any length from short (20px) to long (130px)
    alpha: 0,
    speed,
    width: 0.4 + Math.random() * 2.8,  // any width from very fine (0.4px) to thick and bright (3.2px)
  }
}

export function PremiumBackground({ theme = "dark", mode = "base" }: PremiumBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animRef = useRef<number>(0)
  const themeRef = useRef(theme)
  const modeRef = useRef(mode)
  
  // Preserve entities across renders to prevent resetting on component updates
  const starsRef = useRef<Star[] | null>(null)
  const cometsRef = useRef<Comet[]>([])

  themeRef.current = theme
  modeRef.current = mode

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    let W = window.innerWidth
    let H = window.innerHeight
    canvas.width = W
    canvas.height = H

    const handleResize = () => {
      W = window.innerWidth
      H = window.innerHeight
      canvas.width = W
      canvas.height = H
      if (starsRef.current) {
        starsRef.current.forEach((s) => {
          if (s.x > W) s.x = Math.random() * W
          if (s.y > H) s.y = Math.random() * H
        })
      }
    }
    window.addEventListener("resize", handleResize)

    // Seed dark-mode paid particles once so plan/theme toggles do not reshuffle them.
    if (!starsRef.current) {
      const stars: Star[] = []
      for (let i = 0; i < 350; i++) {
        const x = Math.random() * W
        const y = Math.random() * H
        const phase = Math.random() * Math.PI * 2
        const twinkleSpeed = 0.005 + Math.random() * 0.012

        const rand = Math.random()
        let size = 0.5
        let glow = false
        let alpha = 0.1 + Math.random() * 0.5

        if (rand < 0.80) {
          // Tiny dense background stars
          size = 0.4 + Math.random() * 0.6
        } else if (rand < 0.96) {
          // Medium bright stars
          size = 1.0 + Math.random() * 0.6
          alpha = 0.35 + Math.random() * 0.45
        } else {
          // Rare larger sparkling stars with glowing halos
          size = 1.6 + Math.random() * 0.8
          alpha = 0.6 + Math.random() * 0.4
          glow = true
        }

        stars.push({
          x,
          y,
          size,
          alpha,
          twinkleSpeed,
          phase,
          glow,
        })
      }
      starsRef.current = stars
    }

    const stars = starsRef.current
    const comets = cometsRef.current

    function animate() {
      ctx!.clearRect(0, 0, W, H)
      const shouldDrawPaidParticles = themeRef.current === "dark" && modeRef.current === "comets"

      if (!shouldDrawPaidParticles) {
        comets.length = 0
        animRef.current = requestAnimationFrame(animate)
        return
      }

      // Update and draw stars (Static in position, twinkling organically in place)
      stars.forEach((s) => {
        s.phase += s.twinkleSpeed
        const twinkle = Math.sin(s.phase)
        const currentAlpha = Math.max(0.04, Math.min(1.0, s.alpha + twinkle * 0.28))

        ctx!.save()
        ctx!.beginPath()
        ctx!.arc(s.x, s.y, s.size, 0, Math.PI * 2)

        if (s.glow) {
          ctx!.shadowBlur = 4
          ctx!.shadowColor = "rgba(255, 255, 255, 0.75)"
          ctx!.fillStyle = `rgba(255, 255, 255, ${currentAlpha})`
        } else {
          ctx!.fillStyle = s.size > 1.2 ? `rgba(254, 243, 199, ${currentAlpha})` : `rgba(255, 255, 255, ${currentAlpha})`
        }

        ctx!.fill()
        ctx!.restore()
      })

      // Spawn comets every 15 to 30 seconds on average (average ~20 seconds at 60 FPS)
      if (Math.random() < 0.0008 && comets.length < 2) {
        comets.push(createComet(W, H))
      }

      for (let i = comets.length - 1; i >= 0; i--) {
        const c = comets[i]
        c.x += c.vx
        c.y += c.vy

        if (c.y < H * 0.15) {
          c.alpha = Math.min(0.95, c.alpha + 0.08)
        } else {
          c.alpha = Math.max(0.0, c.alpha - 0.006)
        }

        if (c.alpha > 0) {
          ctx!.save()
          const tailX = c.x - (c.vx / c.speed) * c.length
          const tailY = c.y - (c.vy / c.speed) * c.length

          const grad = ctx!.createLinearGradient(c.x, c.y, tailX, tailY)
          grad.addColorStop(0, `rgba(255, 255, 255, ${c.alpha})`)
          grad.addColorStop(0.15, `rgba(251, 191, 36, ${c.alpha * 0.8})`)
          grad.addColorStop(0.4, `rgba(147, 197, 253, ${c.alpha * 0.3})`)
          grad.addColorStop(1, "rgba(255, 255, 255, 0)")

          ctx!.strokeStyle = grad
          ctx!.lineWidth = c.width + Math.random() * 0.5
          ctx!.lineCap = "round"

          ctx!.beginPath()
          ctx!.moveTo(c.x, c.y)
          ctx!.lineTo(tailX, tailY)
          ctx!.stroke()

          ctx!.fillStyle = `rgba(255, 255, 255, ${c.alpha})`
          ctx!.beginPath()
          ctx!.arc(c.x, c.y, c.width * 1.1, 0, Math.PI * 2)
          ctx!.fill()

          ctx!.restore()
        }

        if (c.x > W + 150 || c.y > H + 150 || c.alpha <= 0) {
          comets.splice(i, 1)
        }
      }

      animRef.current = requestAnimationFrame(animate)
    }

    animate()

    return () => {
      cancelAnimationFrame(animRef.current)
      window.removeEventListener("resize", handleResize)
    }
  }, [])

  const isDark = theme === "dark"
  const showParticles = isDark && mode === "comets"

  return (
    <>
      {/* Base background color */}
      <div
        key={`premium-background-${theme}`}
        className="pointer-events-none fixed inset-0 z-0 transition-colors duration-900 ease-out"
        aria-hidden="true"
        style={{ background: isDark ? "#020206" : "#FDFDFB" }}
      />
      {/* Light-mode schematic structure */}
      <div
        className={`pointer-events-none fixed inset-0 z-[1] transition-opacity duration-900 ease-out ${!isDark ? "opacity-100" : "opacity-0"}`}
        aria-hidden="true"
        style={{
          display: isDark ? "none" : "block",
          backgroundImage: `
            linear-gradient(rgba(20, 23, 31, 0.055) 1px, transparent 1px),
            linear-gradient(90deg, rgba(20, 23, 31, 0.055) 1px, transparent 1px),
            linear-gradient(rgba(20, 23, 31, 0.035) 1px, transparent 1px),
            linear-gradient(90deg, rgba(20, 23, 31, 0.035) 1px, transparent 1px)
          `,
          backgroundPosition: "center",
          backgroundSize: "96px 96px, 96px 96px, 24px 24px, 24px 24px",
        }}
      />
      <div
        className={`pointer-events-none fixed inset-0 z-[2] transition-opacity duration-900 ease-out ${!isDark ? "opacity-100" : "opacity-0"}`}
        aria-hidden="true"
        style={{
          display: isDark ? "none" : "block",
          backgroundImage: `
            radial-gradient(circle at 22% 28%, rgba(79, 70, 229, 0.12), transparent 22%),
            radial-gradient(circle at 82% 18%, rgba(15, 23, 42, 0.07), transparent 18%),
            radial-gradient(circle at 76% 78%, rgba(13, 148, 136, 0.08), transparent 24%),
            repeating-radial-gradient(circle at 18% 82%, rgba(20, 23, 31, 0.08) 0 1px, transparent 1px 18px),
            linear-gradient(118deg, transparent 0 34%, rgba(20, 23, 31, 0.08) 34.1%, transparent 34.5% 100%)
          `,
        }}
      />
      {/* Animation canvas */}
      <canvas
        ref={canvasRef}
        className={`pointer-events-none fixed inset-0 z-[3] transition-opacity duration-900 ease-out ${showParticles ? "opacity-100" : "opacity-0"}`}
        aria-hidden="true"
        style={{ display: showParticles ? "block" : "none" }}
      />
      {/* Subtle noise texture */}
      <div
        className="pointer-events-none fixed inset-0 z-[4] opacity-[0.012]"
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
