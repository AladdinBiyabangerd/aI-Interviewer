import type { Metadata } from "next";
import { Geist } from "next/font/google";
import { headers } from "next/headers";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

const title = "InterviewOS — Structured interview preparation";
const description =
  "Practice role-specific interview questions and receive clear, evidence-based feedback.";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const forwardedHost = requestHeaders.get("x-forwarded-host");
  const rawHost = forwardedHost ?? requestHeaders.get("host") ?? "localhost:3000";
  const host = /^[A-Za-z0-9.-]+(?::\d{1,5})?$/.test(rawHost)
    ? rawHost
    : "localhost:3000";
  const forwardedProtocol = requestHeaders.get("x-forwarded-proto");
  const protocol = forwardedProtocol === "https" || !host.startsWith("localhost")
    ? "https"
    : "http";
  const origin = `${protocol}://${host}`;
  const image = `${origin}/og-minimal-blue.png`;
  return {
    metadataBase: new URL(origin),
    title,
    description,
    openGraph: { title, description, images: [{ url: image, width: 1732, height: 909 }] },
    twitter: { card: "summary_large_image", title, description, images: [image] },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body className={geistSans.variable}>{children}</body></html>;
}
