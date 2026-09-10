import "server-only";

// Keep the public restriction at the handler boundary as well as in Proxy.
// Future interview rollout must deliberately change this server-owned gate.
export function publicInterviewGuard(): Response | null {
  return Response.json({ code: "interview_not_public", message: "Use the Java Q&A assessment." }, {
    status: 410, headers: { "Cache-Control": "no-store" },
  });
}
