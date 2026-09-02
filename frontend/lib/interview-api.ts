import { upload } from "@vercel/blob/client";

export type InterviewStage =
  | "Not sure"
  | "HR / Recruiter"
  | "Technical Interview"
  | "Coding Interview"
  | "System Design"
  | "Hiring Manager"
  | "Final Interview";

export type Seniority = "Not specified" | "Intern" | "Junior" | "Mid-level" | "Senior" | "Lead";
export type InterviewLanguage = "English" | "Azerbaijani";
export type QuestionCategory = "HR / Recruiter" | "CV Questions" | "Technical Questions" | "System Design";
export type QuestionSource = "Company" | "Job Description" | "CV" | "Role" | "Industry" | "Interview Pattern";
export type AnalysisMode = "live_research";

export type ResearchSource = { id: string; title: string; url: string; domain: string };

export type InterviewDetails = {
  company: string;
  role: string;
  jobDescription: string;
  jobUrl: string;
  seniority: Seniority;
  stage: InterviewStage;
  language: InterviewLanguage;
  cvUploadId: string | null;
  cvFileName: string | null;
  cvFileType: string | null;
  cvFileSize: number | null;
};

export type PreparationQuestion = {
  id: string;
  category: QuestionCategory;
  question: string;
  sources: QuestionSource[];
  reason: string;
  approach: string[];
  followUp: string;
  evidence: ResearchSource[];
  specificity: "Company evidence" | "Vacancy" | "Role pattern";
};

export type FocusArea = { label: string; priority: "High" | "Medium" };

export type InterviewAnalysis = {
  id: string;
  createdAt: string;
  details: InterviewDetails;
  companyCoverage: "Limited" | "Strong";
  companyCoverageNote: string;
  analysisMode: AnalysisMode;
  researchSources: ResearchSource[];
  companySignals: Array<{ signal: string; evidence: ResearchSource[] }>;
  focusAreas: FocusArea[];
  cvAreas: FocusArea[];
  questions: PreparationQuestion[];
};

export type PracticeFeedback = { strengths: string[]; improvements: string[]; adaptiveFollowUp: string };
export type PracticeReport = { summary: string; strengths: string[]; improvements: string[]; recommendation: string };
export type PracticeMode = "Real Interview" | "Practice";
export type PracticeFocus = "Full Interview" | "Technical" | "HR / Behavioral" | "CV Deep Dive";
export type PracticeDuration = "15 min" | "30 min" | "45 min";

export const analysisSteps = [
  "Analyzing the role",
  "Reading job requirements",
  "Reviewing your CV",
  "Researching relevant interview signals",
  "Preparing likely questions",
] as const;

type ApiErrorBody = { code?: string };

async function apiError(response: Response): Promise<Error> {
  let body: ApiErrorBody = {};
  try {
    body = await response.json() as ApiErrorBody;
  } catch {
    // The status code remains sufficient when an upstream returned no JSON.
  }
  return new Error(body.code || `request_failed_${response.status}`);
}

function safeFileName(name: string): string {
  const normalized = name.normalize("NFKC").replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
  return normalized.slice(-180) || "cv.pdf";
}

export async function uploadCv(
  file: File,
  onProgress?: (percentage: number) => void,
): Promise<Pick<InterviewDetails, "cvUploadId" | "cvFileName" | "cvFileType" | "cvFileSize">> {
  const uploadId = crypto.randomUUID();
  const blob = await upload(`cv/${uploadId}/${safeFileName(file.name)}`, file, {
    access: "private",
    handleUploadUrl: "/api/cv/upload",
    clientPayload: JSON.stringify({ uploadId }),
    multipart: true,
    onUploadProgress: ({ percentage }) => onProgress?.(percentage),
  });
  return {
    cvUploadId: uploadId,
    cvFileName: file.name,
    cvFileType: blob.contentType || file.type,
    cvFileSize: file.size,
  };
}

const wait = (milliseconds: number) => new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));

export async function prepareInterview(
  details: InterviewDetails,
  onStep: (stepIndex: number) => void,
): Promise<InterviewAnalysis> {
  const response = await fetch("/api/interview-preparations/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(details),
  });
  if (!response.ok) throw await apiError(response);
  const started = await response.json() as { jobId: string };
  const startedAt = Date.now();
  for (let attempt = 0; attempt < 300; attempt += 1) {
    onStep(Math.min(analysisSteps.length - 1, Math.floor((Date.now() - startedAt) / 4_000)));
    await wait(attempt === 0 ? 500 : 2_000);
    const status = await fetch(`/api/interview-preparations/analyze/${encodeURIComponent(started.jobId)}`, { cache: "no-store" });
    if (!status.ok) throw await apiError(status);
    const body = await status.json() as { status: string; analysis?: InterviewAnalysis };
    if (body.status === "completed" && body.analysis) {
      onStep(analysisSteps.length - 1);
      return body.analysis;
    }
    if (body.status === "failed") throw new Error("analysis_failed");
  }
  throw new Error("analysis_timeout");
}

export async function loadRecentPreparation(): Promise<InterviewAnalysis | null> {
  const response = await fetch("/api/interview-preparations/recent", { cache: "no-store" });
  if (!response.ok) return null;
  const body = await response.json() as { analysis?: InterviewAnalysis | null };
  return body.analysis ?? null;
}

export async function startPractice(input: {
  preparationId: string;
  mode: PracticeMode;
  focus: PracticeFocus;
  duration: PracticeDuration;
  questionIds: string[];
}): Promise<{ sessionId: string }> {
  const response = await fetch("/api/practice-sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw await apiError(response);
  return response.json() as Promise<{ sessionId: string }>;
}

export async function submitPracticeAnswer(input: { sessionId: string; answer: string }): Promise<{
  feedback: PracticeFeedback;
  followUp: string | null;
  nextQuestion: boolean;
  sessionComplete: boolean;
}> {
  const response = await fetch(`/api/practice-sessions/${encodeURIComponent(input.sessionId)}/answers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer: input.answer }),
  });
  if (!response.ok) throw await apiError(response);
  return response.json();
}

export async function finishPracticeSession(sessionId: string): Promise<PracticeReport> {
  const response = await fetch(`/api/practice-sessions/${encodeURIComponent(sessionId)}/complete`, { method: "POST" });
  if (!response.ok) throw await apiError(response);
  const body = await response.json() as { report: PracticeReport };
  return body.report;
}
