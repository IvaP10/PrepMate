import type { Metadata, Viewport } from 'next'
import { Geist, Geist_Mono, DM_Serif_Display } from 'next/font/google'
import { Toaster } from 'sonner'
import './globals.css'
const geistSans = Geist({
  subsets: ['latin'],
  variable: '--font-geist-sans',
})
const dmSerif = DM_Serif_Display({
  weight: '400',
  subsets: ['latin'],
  variable: '--font-serif',
})
const geistMono = Geist_Mono({
  subsets: ['latin'],
  variable: '--font-geist-mono',
})
export const metadata: Metadata = {
  title: 'InterAI',
  description: 'Ace your next interview with personalized AI coaching powered by your resume.',
  icons: {
    icon: [
      { url: '/images/ligh.png', type: 'image/png', sizes: '20x20' },
    ],
    apple: { url: '/images/ligh.png', sizes: '20x20' },
  },
}
export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#ffffff' },
    { media: '(prefers-color-scheme: dark)', color: '#111111' },
  ],
}
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${dmSerif.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var t = localStorage.getItem('interai-theme');
                  if (t === 'dark') {
                    document.documentElement.classList.add('dark');
                  } else if (t === 'light') {
                    document.documentElement.classList.remove('dark');
                  } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
                    document.documentElement.classList.add('dark');
                  }
                } catch(e) {}
              })();
            `,
          }}
        />
      </head>
      <body className="font-sans antialiased">
        {children}
        <Toaster
          toastOptions={{
            className: 'bg-card text-card-foreground border-border',
          }}
        />
      </body>
    </html>
  )
}
