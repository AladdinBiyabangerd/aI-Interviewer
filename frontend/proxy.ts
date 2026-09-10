import { NextResponse } from "next/server";

// The Q&A MVP does not expose the former open-ended interview or AI generation
// endpoints. Preserve the implementation for future work without public access.
export function proxy() {
  return NextResponse.json({ code: "interview_not_public", message: "Use the Java Q&A assessment." }, { status: 410 });
}
export const config = {
  matcher: ["/api/practice-sessions/:path*", "/api/interview-preparations/:path*", "/api/cv/:path*", "/api/webhooks/openai/:path*"],
};
