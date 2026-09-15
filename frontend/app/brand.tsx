import Image from "next/image";
import Link from "next/link";

export function Brand() {
  return <Link className="brand" href="/" aria-label="AI Interviewer">
    <Image
      src="/ai-interviewer-logo.svg"
      alt="AI Interviewer"
      width={455}
      height={84}
      loading="eager"
      unoptimized
    />
  </Link>;
}
