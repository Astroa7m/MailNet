import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { headers } from "next/headers";
import ChatProvider from "./components/ChatProvider";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "MailNet",
  description: "AI-powered email assistant",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // proxy.ts puts a per-request nonce here; the inline theme script below
  // must carry it or the Content Security Policy blocks it.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: `(function(){try{var t=localStorage.getItem('mailnet-theme');if(t==='light'){document.documentElement.classList.remove('dark');}else{document.documentElement.classList.add('dark');}}catch(e){document.documentElement.classList.add('dark');}})();` }} />
      </head>
      <body className="h-full w-full">
        <ChatProvider>
          {children}
        </ChatProvider>
      </body>
    </html>
  );
}
