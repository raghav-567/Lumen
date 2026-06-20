import type { Metadata } from 'next';
import '@/styles/globals.css';
import DemoBanner from '@/components/DemoBanner';

export const metadata: Metadata = {
  title: 'KnowledgeDrift — AI Knowledge Drift Detection',
  description:
    'Detect contradictions, outdated information, and semantic inconsistencies across your document collections using AI.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        {children}
        <DemoBanner />
      </body>
    </html>
  );
}
