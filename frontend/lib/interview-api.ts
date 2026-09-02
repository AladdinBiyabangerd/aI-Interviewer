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
export type AnalysisMode = "live_research" | "local_preview";

export type ResearchSource = {
  id: string;
  title: string;
  url: string;
  domain: string;
};

export type QuestionEvidence = ResearchSource;

export type InterviewDetails = {
  company: string;
  role: string;
  jobDescription: string;
  jobUrl: string;
  seniority: Seniority;
  stage: InterviewStage;
  language: InterviewLanguage;
  cvFileName: string | null;
  cvFileType?: string | null;
  cvFileData?: string | null;
};

export type PreparationQuestion = {
  id: string;
  category: QuestionCategory;
  question: string;
  sources: QuestionSource[];
  reason: string;
  approach: string[];
  followUp: string;
  evidence: QuestionEvidence[];
  specificity: "Company evidence" | "Vacancy" | "Role pattern";
};

export type FocusArea = {
  label: string;
  priority: "High" | "Medium";
};

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

export const analysisSteps = [
  "Analyzing the role",
  "Reading job requirements",
  "Reviewing your CV",
  "Researching relevant interview signals",
  "Preparing likely questions",
] as const;

const API_BASE_URL = process.env.NEXT_PUBLIC_INTERVIEW_API_BASE_URL?.replace(/\/$/, "");

const wait = (milliseconds: number) =>
  new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));

function includesAny(text: string, terms: string[]): boolean {
  const normalized = text.toLocaleLowerCase("en-US");
  return terms.some((term) => normalized.includes(term));
}

function buildTechnicalQuestions(details: InterviewDetails): PreparationQuestion[] {
  const context = `${details.role} ${details.jobDescription}`;
  const questions: PreparationQuestion[] = [];

  if (includesAny(context, ["rag", "retrieval", "llm", "language model", "vector"])) {
    questions.push(
      {
        id: "rag-architecture",
        category: "Technical Questions",
        question:
          "Walk me through how you would design a production RAG system, from document ingestion to the final response.",
        sources: ["Job Description", "Role"],
        reason:
          "The vacancy emphasizes applied AI systems, so architecture choices and the boundaries between retrieval and generation are likely to be explored.",
        approach: ["Define the use case", "Cover ingestion and retrieval", "Explain trade-offs", "Close with evaluation and monitoring"],
        followUp: "How would you evaluate retrieval quality independently from the final LLM response?",
        evidence: [],
        specificity: "Vacancy",
      },
      {
        id: "rag-evaluation",
        category: "Technical Questions",
        question: "How would you evaluate retrieval quality before deploying a RAG system into production?",
        sources: ["Job Description", "Interview Pattern"],
        reason:
          "Evaluation distinguishes a working prototype from a reliable production system and directly tests technical depth.",
        approach: ["Separate retrieval and generation", "Choose relevant metrics", "Build an evaluation set", "Monitor production drift"],
        followUp: "How would your evaluation change if you had no labeled relevance data?",
        evidence: [],
        specificity: "Vacancy",
      },
    );
  }

  if (includesAny(context, ["python", "fastapi", "backend", "api"])) {
    questions.push({
      id: "api-reliability",
      category: "Technical Questions",
      question: "How would you investigate an API whose latency rises sharply under peak traffic?",
      sources: ["Job Description", "Role"],
      reason:
        "The role calls for backend ownership, making performance diagnosis and safe production decision-making relevant.",
      approach: ["Establish symptoms and impact", "Use traces and saturation metrics", "Test competing hypotheses", "Validate a safe change"],
      followUp: "Which signal would help you distinguish database saturation from application-level contention?",
      evidence: [],
      specificity: "Vacancy",
    });
  }

  if (includesAny(context, ["deploy", "production", "docker", "kubernetes", "monitor"])) {
    questions.push({
      id: "production-deployment",
      category: "System Design",
      question: "How would you deploy and monitor this system in production while limiting rollout risk?",
      sources: ["Job Description", "Role"],
      reason:
        "Production and deployment requirements usually lead to questions about observability, rollout controls, and operational ownership.",
      approach: ["Describe the release path", "Define service-level signals", "Limit blast radius", "Explain rollback criteria"],
      followUp: "What would make you stop or roll back the deployment?",
      evidence: [],
      specificity: "Vacancy",
    });
  }

  if (questions.length < 3) {
    questions.push(
      {
        id: "technical-tradeoff",
        category: "Technical Questions",
        question: `Describe a difficult technical decision you would expect to own as a ${details.role}. How would you compare the alternatives?`,
        sources: ["Role", "Interview Pattern"],
        reason:
          "The question tests whether you can connect technical choices to constraints instead of presenting one solution as universally correct.",
        approach: ["State the decision", "Name the constraints", "Compare credible options", "Explain the measured outcome"],
        followUp: "What new information would cause you to reverse that decision?",
        evidence: [],
        specificity: "Role pattern",
      },
      {
        id: "failure-analysis",
        category: "System Design",
        question: "A critical service fails unexpectedly. What do you do in the first 30 minutes?",
        sources: ["Role", "Industry"],
        reason:
          "Operational judgment is a common signal for roles that own production systems, particularly in regulated or high-availability environments.",
        approach: ["Protect customers", "Assign ownership", "Gather high-signal evidence", "Communicate and recover"],
        followUp: "How would you keep the incident response moving when the root cause is still unclear?",
        evidence: [],
        specificity: "Role pattern",
      },
    );
  }

  return questions.slice(0, 4);
}

function buildQuestions(details: InterviewDetails): PreparationQuestion[] {
  const cvQuestions: PreparationQuestion[] = details.cvFileName
    ? [
        {
          id: "cv-project",
          category: "CV Questions",
          question: `Choose the project in your CV that best demonstrates your readiness for this ${details.role} role. What did you personally own?`,
          sources: ["CV", "Role"],
          reason:
            "Interviewers commonly test the strongest role-relevant claim in a CV and clarify the candidate's individual contribution.",
          approach: ["Set the project context", "Make your ownership explicit", "Explain one key decision", "Quantify the result"],
          followUp: "Which part of that outcome can be attributed specifically to your decisions?",
          evidence: [],
          specificity: "Role pattern",
        },
        {
          id: "cv-depth",
          category: "CV Questions",
          question: "Which technical claim in your CV would be hardest to reproduce today, and what did you learn from it?",
          sources: ["CV", "Interview Pattern"],
          reason:
            "This explores depth behind written claims without assuming details that have not been verified from the uploaded file.",
          approach: ["Name the claim", "Describe the real constraint", "Explain the hard part", "Share what changed in your approach"],
          followUp: "What evidence did you use to know the solution was working?",
          evidence: [],
          specificity: "Role pattern",
        },
      ]
    : [];

  const technical = buildTechnicalQuestions(details);
  const general: PreparationQuestion[] = [
    {
      id: "introduction",
      category: "HR / Recruiter",
      question: `Tell me about yourself and walk me through the experience most relevant to this ${details.role} role.`,
      sources: details.cvFileName ? ["CV", "Role"] : ["Role", "Interview Pattern"],
      reason:
        "A concise introduction helps the interviewer connect your background to the role before exploring specific evidence.",
      approach: ["Start with your current focus", "Select two relevant experiences", "Connect them to this role", "Keep the answer concise"],
      followUp: "Which of those experiences best reflects the work you want to do next?",
      evidence: [],
      specificity: "Role pattern",
    },
    {
      id: "company-motivation",
      category: "HR / Recruiter",
      question: `Why are you interested in ${details.company} and this ${details.role} position?`,
      sources: ["Company", "Role"],
      reason:
        "Motivation and company fit are commonly explored, but the answer should rely on facts you have personally verified.",
      approach: ["Name a verified company reason", "Connect it to the role", "Explain your contribution", "Avoid generic praise"],
      followUp: "What would make this role a meaningful next step for you?",
      evidence: [],
      specificity: "Role pattern",
    },
    {
      id: "behavioral-conflict",
      category: "HR / Recruiter",
      question: "Tell me about a disagreement over a technical decision and how you helped the team reach a conclusion.",
      sources: ["Role", "Interview Pattern"],
      reason:
        "The question tests collaboration, evidence-based decision-making, and ownership rather than technical knowledge alone.",
      approach: ["Give the situation", "Explain the competing views", "Show your action", "End with the result and lesson"],
      followUp: "What would you do differently if the same disagreement happened now?",
      evidence: [],
      specificity: "Role pattern",
    },
  ];

  return [...cvQuestions, ...technical, ...general].slice(0, 9);
}

function localizeQuestions(questions: PreparationQuestion[], details: InterviewDetails): PreparationQuestion[] {
  if (details.language !== "Azerbaijani") return questions;

  const text: Record<string, Pick<PreparationQuestion, "question" | "reason" | "approach" | "followUp">> = {
    "rag-architecture": {
      question: "Sənədlərin qəbulundan yekun cavaba qədər production səviyyəli RAG sistemini necə dizayn edərdiniz?",
      reason: "Vakansiya tətbiqi AI sistemlərini vurğulayır. Buna görə arxitektura seçimləri, retrieval və generation sərhədləri yoxlanıla bilər.",
      approach: ["İstifadə ssenarisini müəyyən edin", "Məlumat qəbulu və retrieval hissəsini izah edin", "Trade-off-ları göstərin", "Qiymətləndirmə və monitorinqlə tamamlayın"],
      followUp: "Yekun LLM cavabından asılı olmadan retrieval keyfiyyətini necə qiymətləndirərdiniz?",
    },
    "rag-evaluation": {
      question: "RAG sistemini production mühitinə çıxarmazdan əvvəl retrieval keyfiyyətini necə qiymətləndirərdiniz?",
      reason: "Qiymətləndirmə işlək prototipi etibarlı production sistemindən ayırır və texniki dərinliyi birbaşa yoxlayır.",
      approach: ["Retrieval və generation qiymətləndirməsini ayırın", "Uyğun metrikləri seçin", "Qiymətləndirmə dəsti yaradın", "Production dəyişikliklərini izləyin"],
      followUp: "İşarələnmiş relevance məlumatınız olmasaydı, qiymətləndirməni necə dəyişərdiniz?",
    },
    "api-reliability": {
      question: "Pik trafik zamanı gecikməsi kəskin artan API-ni necə araşdırardınız?",
      reason: "Vəzifə backend məsuliyyətini tələb edir. Buna görə performans diaqnostikası və təhlükəsiz production qərarları vacibdir.",
      approach: ["Simptom və təsiri müəyyən edin", "Trace və saturation metriklərindən istifadə edin", "Alternativ hipotezləri yoxlayın", "Təhlükəsiz dəyişikliyi təsdiqləyin"],
      followUp: "Database yüklənməsini tətbiq səviyyəsindəki resurs rəqabətindən hansı siqnal ilə ayırardınız?",
    },
    "production-deployment": {
      question: "Rollout riskini məhdudlaşdırmaqla bu sistemi production mühitinə necə yerləşdirib izləyərdiniz?",
      reason: "Production və deployment tələbləri observability, rollout nəzarəti və əməliyyat məsuliyyəti haqqında suallar yaradır.",
      approach: ["Release prosesini izah edin", "Xidmət səviyyəsi siqnallarını müəyyən edin", "Təsir dairəsini məhdudlaşdırın", "Rollback meyarlarını açıqlayın"],
      followUp: "Hansı vəziyyətdə deployment-i dayandırar və ya geri qaytarardınız?",
    },
    "technical-tradeoff": {
      question: `${details.role} kimi məsul olacağınız çətin texniki qərarı təsvir edin. Alternativləri necə müqayisə edərdiniz?`,
      reason: "Bu sual bir həlli universal düzgün kimi təqdim etmək əvəzinə texniki seçimləri məhdudiyyətlərlə əlaqələndirmək bacarığını yoxlayır.",
      approach: ["Qərarı müəyyən edin", "Məhdudiyyətləri sadalayın", "Real alternativləri müqayisə edin", "Ölçülmüş nəticəni izah edin"],
      followUp: "Hansı yeni məlumat bu qərarı dəyişməyinizə səbəb olardı?",
    },
    "failure-analysis": {
      question: "Kritik xidmət gözlənilmədən dayanır. İlk 30 dəqiqədə nə edərdiniz?",
      reason: "Production sistemlərinə cavabdeh vəzifələrdə, xüsusilə yüksək əlçatanlıq tələb olunan sahələrdə əməliyyat mühakiməsi vacib siqnaldır.",
      approach: ["İstifadəçiləri qoruyun", "Məsuliyyəti bölüşdürün", "Yüksək siqnallı məlumat toplayın", "Kommunikasiya qurub xidməti bərpa edin"],
      followUp: "Kök səbəb hələ məlum olmayanda insident prosesini necə hərəkətdə saxlayardınız?",
    },
    "cv-project": {
      question: `CV-nizdə ${details.role} vəzifəsinə hazırlığınızı ən yaxşı göstərən layihəni seçin. Şəxsən hansı hissəyə cavabdeh idiniz?`,
      reason: "Müsahibəçilər adətən CV-də vəzifəyə ən uyğun iddianı yoxlayır və namizədin şəxsi töhfəsini dəqiqləşdirirlər.",
      approach: ["Layihənin kontekstini verin", "Şəxsi məsuliyyətinizi aydın göstərin", "Əsas qərarlardan birini izah edin", "Nəticəni rəqəmlərlə göstərin"],
      followUp: "Bu nəticənin hansı hissəsi konkret olaraq sizin qərarlarınızla bağlı idi?",
    },
    "cv-depth": {
      question: "CV-nizdəki hansı texniki iddianı bu gün yenidən həyata keçirmək daha çətin olardı və ondan nə öyrəndiniz?",
      reason: "Bu sual yüklənmiş faylda təsdiqlənməmiş detalları fərz etmədən yazılı iddiaların arxasındakı dərinliyi araşdırır.",
      approach: ["İddianı müəyyən edin", "Real məhdudiyyəti izah edin", "Çətin hissəni göstərin", "Yanaşmanızda nəyin dəyişdiyini paylaşın"],
      followUp: "Həllin işlədiyini bilmək üçün hansı sübutlardan istifadə etdiniz?",
    },
    introduction: {
      question: `Özünüz haqqında danışın və ${details.role} vəzifəsinə ən uyğun təcrübənizi izah edin.`,
      reason: "Qısa təqdimat müsahibəçiyə konkret sübutlara keçməzdən əvvəl təcrübənizi vəzifə ilə əlaqələndirməyə kömək edir.",
      approach: ["Hazırkı fokusunuzla başlayın", "İki uyğun təcrübə seçin", "Onları bu vəzifə ilə əlaqələndirin", "Cavabı qısa saxlayın"],
      followUp: "Bu təcrübələrdən hansı növbəti mərhələdə görmək istədiyiniz işi daha yaxşı əks etdirir?",
    },
    "company-motivation": {
      question: `${details.company} şirkəti və ${details.role} vəzifəsi ilə niyə maraqlanırsınız?`,
      reason: "Motivasiya və şirkətə uyğunluq adətən yoxlanılır, lakin cavab şəxsən təsdiqlədiyiniz faktlara əsaslanmalıdır.",
      approach: ["Təsdiqlənmiş şirkət səbəbi göstərin", "Onu vəzifə ilə əlaqələndirin", "Töhfənizi izah edin", "Ümumi təriflərdən qaçın"],
      followUp: "Bu vəzifəni sizin üçün mənalı növbəti addıma nə çevirərdi?",
    },
    "behavioral-conflict": {
      question: "Texniki qərarla bağlı fikir ayrılığını və komandanın nəticəyə gəlməsinə necə kömək etdiyinizi danışın.",
      reason: "Bu sual yalnız texniki biliyi deyil, əməkdaşlığı, sübuta əsaslanan qərarverməni və məsuliyyəti yoxlayır.",
      approach: ["Vəziyyəti təsvir edin", "Fərqli mövqeləri izah edin", "Atdığınız addımı göstərin", "Nəticə və öyrəndiyiniz dərslə tamamlayın"],
      followUp: "Eyni fikir ayrılığı indi baş versəydi, nəyi fərqli edərdiniz?",
    },
  };

  return questions.map((question) => ({ ...question, ...(text[question.id] ?? {}) }));
}

function buildLocalAnalysis(details: InterviewDetails): InterviewAnalysis {
  const context = `${details.role} ${details.jobDescription}`;
  const focusAreas: FocusArea[] = [];
  if (includesAny(context, ["rag", "retrieval", "llm", "language model"])) {
    focusAreas.push({ label: "RAG / LLM systems", priority: "High" });
  }
  if (includesAny(context, ["python", "fastapi", "backend", "api"])) {
    focusAreas.push({ label: "Python and API engineering", priority: "High" });
  }
  if (includesAny(context, ["deploy", "production", "docker", "kubernetes"])) {
    focusAreas.push({ label: "Production deployment", priority: "High" });
  }
  focusAreas.push(
    { label: "Technical decision-making", priority: focusAreas.length ? "Medium" : "High" },
    { label: "Clear evidence and outcomes", priority: "Medium" },
  );

  return {
    id: `prep-${Date.now()}`,
    createdAt: new Date().toISOString(),
    details,
    companyCoverage: "Limited",
    companyCoverageNote:
      "Public interview information for this company is limited. Questions are weighted more heavily toward the vacancy, role, industry and your CV.",
    analysisMode: "local_preview",
    researchSources: [],
    companySignals: [],
    focusAreas: focusAreas.slice(0, 5),
    cvAreas: details.cvFileName
      ? [
          { label: "Project ownership", priority: "High" },
          { label: "Technical decisions", priority: "High" },
          { label: "Measured outcomes", priority: "Medium" },
        ]
      : [],
    questions: localizeQuestions(buildQuestions(details), details),
  };
}

export async function prepareInterview(
  details: InterviewDetails,
  onStep: (stepIndex: number) => void,
): Promise<InterviewAnalysis> {
  const endpoint = API_BASE_URL
    ? `${API_BASE_URL}/api/v1/interview-preparations/analyze`
    : "/api/interview-preparations/analyze";

  for (let index = 0; index < analysisSteps.length - 1; index += 1) {
    onStep(index);
    await wait(160);
  }
  onStep(analysisSteps.length - 1);

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(details),
    });
    if (response.ok) {
      return (await response.json()) as InterviewAnalysis;
    }
    if (API_BASE_URL) {
      throw new Error("We could not prepare this interview. Please check the details and try again.");
    }
  } catch (error) {
    if (API_BASE_URL) throw error;
  }

  await wait(240);
  return buildLocalAnalysis(details);
}
