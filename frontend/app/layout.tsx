import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

const title = "Interview Prep — Prepare for the questions that matter";
const description =
  "Prepare likely questions for a specific company, role and vacancy, then practise them in a focused interview.";

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
  openGraph: { title, description, images: [{ url: "/og.png", width: 1732, height: 909 }] },
  twitter: { card: "summary_large_image", title, description, images: ["/og.png"] },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={geistSans.variable}>{children}</body>
    </html>
  );
}
