import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {title: '모두라우터', description: '질문하고, 자료를 읽고, 함께 이해하는 한국어 AI'};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="ko"><body>{children}</body></html>;
}
