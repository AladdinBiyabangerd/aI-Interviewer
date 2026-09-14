import type { Metadata } from "next";

const title = "Java müsahibəsinə hazırlıq — Intervia";
const description = "Java və backend biliklərinizi yoxlayın, Java 8 kitabı üzrə məşq edin və cavablarınızı testin sonunda nəzərdən keçirin.";

export const metadata: Metadata = {
  title,
  description,
  openGraph: { title, description },
  twitter: { title, description },
};

export default function JavaLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
