import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";

import "./globals.css";
import "./design-system.css";
import "./editorial-design.css";

const geist = Geist({
  subsets: ["latin"],
  variable: "--font-geist-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "SophIA — sua assistente financeira",
  description: "Sua assistente financeira pessoal e privada.",
  applicationName: "SophIA",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/icon.svg",
  },
};

export const viewport: Viewport = {
  themeColor: "#315e49",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR">
      <body className={geist.variable}>{children}</body>
    </html>
  );
}
