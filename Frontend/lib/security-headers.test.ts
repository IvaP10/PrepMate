import { describe, expect, it } from "vitest"

describe("frontend security headers", () => {
  it("ships a restrictive CSP without wildcard sources", async () => {
    const { default: nextConfig } = await import("../next.config.mjs")
    expect(nextConfig.poweredByHeader).toBe(false)
    const rules = await nextConfig.headers()
    const headers = Object.fromEntries(rules[0].headers.map(({ key, value }) => [key, value]))
    const csp = headers["Content-Security-Policy"]

    expect(csp).toContain("default-src 'self'")
    expect(csp).toContain("object-src 'none'")
    expect(csp).toContain("frame-ancestors 'none'")
    expect(csp).toContain("http://127.0.0.1:*")
    expect(csp).toContain("ws://127.0.0.1:*")
    expect(csp).not.toContain("connect-src 'self' https:")
    expect(csp).not.toContain("accounts.google.com")
    expect(csp).not.toContain("checkout.razorpay.com")
    expect(csp).not.toContain("upgrade-insecure-requests")
    expect(csp).not.toMatch(/(?:^|\s)\*(?:\s|;|$)/)
    expect(headers["X-Content-Type-Options"]).toBe("nosniff")
    expect(headers["Cross-Origin-Opener-Policy"]).toBe("same-origin")
    expect(headers["Permissions-Policy"]).toContain("display-capture=(self)")
  })
})
