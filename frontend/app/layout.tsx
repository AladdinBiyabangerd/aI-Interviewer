import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

const title = "Interview Prep — Check your Java knowledge";
const description =
  "Assess your Java knowledge with adaptive choice-based questions, instant scores and a focused study plan for Junior, Mid and Senior engineers.";

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
  openGraph: { title, description },
  twitter: { card: "summary", title, description },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={geistSans.variable}>{children}</body>
    </html>
  );
}
