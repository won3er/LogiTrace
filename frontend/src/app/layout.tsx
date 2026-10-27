import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppShell } from "@/components/app-shell";
import { Providers } from "@/components/providers";

import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

const geistSans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "LogiTrace — Inteligência Logística do Brasil",
  description:
    "Plataforma de inteligência logística, análise territorial, redes de transporte, simulação de cenários e otimização para o Brasil.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="pt-BR" className={`dark ${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="h-full overflow-hidden">
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
