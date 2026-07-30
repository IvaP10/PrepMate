interface PremiumBackgroundProps {
  theme?: "light" | "dark"
  mode?: "base" | "comets"
}

export function PremiumBackground({ theme = "dark", mode = "base" }: PremiumBackgroundProps) {
  return (
    <div
      className="premium-background-frame pointer-events-none fixed inset-0 z-0 overflow-hidden"
      data-theme={theme}
      aria-hidden="true"
    >
      <div
        className="premium-background-base absolute inset-0 z-0"
        data-theme={theme}
      />

      <div
        className="premium-background-ambience premium-background-ambience-light absolute inset-0 z-[1]"
      />

      <div
        className="premium-background-ambience premium-background-ambience-dark absolute inset-0 z-[1]"
      />

      <svg
        className={`premium-background-geometry absolute inset-0 z-[2] h-full w-full ${mode === "base" ? "opacity-35" : ""}`}
        viewBox="0 0 1600 1000"
        preserveAspectRatio="xMidYMid slice"
        fill="none"
        aria-hidden="true"
      >
        <g className="premium-background-orbits">
          <circle cx="-110" cy="640" r="300" />
          <circle cx="-110" cy="640" r="500" />
          <circle cx="-110" cy="640" r="720" />
          <circle cx="-110" cy="640" r="940" />
        </g>

        <g className="premium-background-dashed-orbit">
          <circle cx="-110" cy="640" r="610" />
        </g>

        <g className="premium-background-sweeps">
          <path d="M-180 182C358 62 1028 178 1765 492" />
          <path d="M-180 430C390 286 1080 396 1760 704" />
          <path d="M-140 720C456 542 1124 618 1740 912" />
        </g>

        <g className="premium-background-construction-lines">
          <path d="M905-150L-70 804" />
          <path d="M1550-120L470 1080" />
          <path d="M1220-120L154 1080" />
        </g>
      </svg>

      <div
        className="absolute inset-0 z-[3] opacity-[0.012]"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
          backgroundRepeat: "repeat",
          backgroundSize: "128px 128px",
        }}
      />
    </div>
  )
}
