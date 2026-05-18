import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Document Q&A Assistant',
  description: 'AI-powered document analysis and intelligent question answering',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50 font-sans antialiased">
        {children}
      </body>
    </html>
  )
}