import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

const DESKTOP_HEADER = "x-prepmate-desktop-token"

export function proxy(request: NextRequest) {
  const expectedToken = process.env.PREPMATE_DESKTOP_TOKEN
  const providedToken = request.headers.get(DESKTOP_HEADER)

  if (!expectedToken || providedToken !== expectedToken) {
    return new NextResponse("PrepMate is a desktop application.", {
      status: 403,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": "text/plain; charset=utf-8",
      },
    })
  }

  return NextResponse.next()
}
