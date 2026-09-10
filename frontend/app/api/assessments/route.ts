import { assessmentRequest } from "../../../lib/server/assessment-store";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const GET = (request: Request) => assessmentRequest(request);
export const POST = (request: Request) => assessmentRequest(request);
