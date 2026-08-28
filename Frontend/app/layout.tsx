import type { Metadata, Viewport } from 'next'
import Script from 'next/script'
import { Toaster } from 'sonner'
import './globals.css'
export const metadata: Metadata = {
  title: 'PrepMate',
  description: 'Practice interviews with private, local-first coaching powered by your chosen AI provider.',
  icons: {
    icon: [
      {
        url: '/images/light.svg',
        type: 'image/svg+xml',
        sizes: 'any',
        media: '(prefers-color-scheme: light)',
      },
      {
        url: '/images/logo-dark.svg',
        type: 'image/svg+xml',
        sizes: 'any',
        media: '(prefers-color-scheme: dark)',
      },
    ],
    apple: [
      { url: '/images/light.svg', sizes: 'any', media: '(prefers-color-scheme: light)' },
      { url: '/images/logo-dark.svg', sizes: 'any', media: '(prefers-color-scheme: dark)' },
    ],
  },
}
export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#F7F8F6' },
    { media: '(prefers-color-scheme: dark)', color: '#0B0F0E' },
  ],
}
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" data-scroll-behavior="smooth" suppressHydrationWarning>
      <body className="min-h-dvh bg-background font-sans antialiased">
        <Script src="/theme-init.js" strategy="beforeInteractive" />
        {children}
        <Toaster
          position="bottom-right"
          closeButton
          toastOptions={{
            classNames: {
              toast: "toast-premium group",
              title: "text-foreground font-medium",
              description: "text-muted-foreground",
              closeButton: "toast-close-btn",
            },
          }}
        />
      </body>
    </html>
  )
}
