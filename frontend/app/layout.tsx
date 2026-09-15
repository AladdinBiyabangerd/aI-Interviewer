import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

const title = "AI Interviewer — Müsahibəyə hazır gir";
const description =
  "AI Interviewer ilə müsahibəyə hazırlaşın. İstiqamətinizi seçin, öz tempinizdə məşq edin və nəticələrinizi sonda nəzərdən keçirin.";

const configuredOrigin = process.env.NEXT_PUBLIC_APP_URL?.trim();
const vercelHost = process.env.VERCEL_PROJECT_PRODUCTION_URL || process.env.VERCEL_URL;
const metadataBase = configuredOrigin
  ? new URL(configuredOrigin)
  : vercelHost
    ? new URL(`https://${vercelHost}`)
    : new URL("https://interview-prep.invalid");

export const metadata: Metadata = {
  metadataBase,
  title,
  description,
  icons: { icon: "/favicon.svg" },
  openGraph: { title, description, type: "website", locale: "az_AZ" },
  twitter: { card: "summary_large_image", title, description, images: ["/opengraph-image"] },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="az">
      <body className={geistSans.variable}>{children}</body>
    </html>
  );
}
