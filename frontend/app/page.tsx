"use client";

import { ChangeEvent, FormEvent, useMemo, useRef, useState } from "react";

import {
  analysisSteps,
  InterviewAnalysis,
  InterviewDetails,
  InterviewLanguage,
  InterviewStage,
  PreparationQuestion,
  prepareInterview,
  QuestionCategory,
  Seniority,
} from "../lib/interview-api";

type View =
  | "home"
  | "form"
  | "analyzing"
  | "overview"
  | "questions"
  | "practice-setup"
  | "practice-active"
  | "report";
type PracticeMode = "Real Interview" | "Practice";
type PracticeFocus = "Full Interview" | "Technical" | "HR / Behavioral" | "CV Deep Dive";
type Duration = "15 min" | "30 min" | "45 min";

const initialDetails: InterviewDetails = {
  company: "",
  role: "",
  jobDescription: "",
  jobUrl: "",
  seniority: "Not specified",
  stage: "Not sure",
  language: "English",
  cvFileName: null,
};

const seniorities: Seniority[] = ["Not specified", "Intern", "Junior", "Mid-level", "Senior", "Lead"];
const stages: InterviewStage[] = [
  "Not sure",
  "HR / Recruiter",
  "Technical Interview",
  "Coding Interview",
  "System Design",
  "Hiring Manager",
  "Final Interview",
];

function Brand({ onClick }: { onClick: () => void }) {
  return (
    <button className="brand" type="button" onClick={onClick} aria-label="Interview Prep home">
      <span aria-hidden="true">IP</span>
      Interview Prep
    </button>
  );
}

function Header({
  analysis,
  activeView,
  onNavigate,
}: {
  analysis: InterviewAnalysis | null;
  activeView: View;
  onNavigate: (view: View) => void;
}) {
  const preparedView = ["overview", "questions", "practice-setup", "practice-active", "report"].includes(activeView);
  return (
    <header className="site-header">
      <div className="header-inner">
        <Brand onClick={() => onNavigate("home")} />
        {analysis && preparedView ? (
          <nav className="preparation-nav" aria-label="Interview preparation">
            <button className={activeView === "overview" ? "active" : ""} onClick={() => onNavigate("overview")} type="button">Overview</button>
            <button className={activeView === "questions" ? "active" : ""} onClick={() => onNavigate("questions")} type="button">Questions</button>
            <button className={activeView.startsWith("practice") ? "active" : ""} onClick={() => onNavigate("practice-setup")} type="button">Practice</button>
          </nav>
        ) : null}
        <button className="header-action" type="button" onClick={() => onNavigate("form")}>New preparation</button>
      </div>
    </header>
  );
}

function Home({ recent, onStart, onOpen }: { recent: InterviewAnalysis | null; onStart: () => void; onOpen: () => void }) {
  return (
    <main className="page home-page">
      <section className="home-intro">
        <p className="eyebrow">Interview preparation</p>
        <h1>Prepare for your interview</h1>
        <p className="home-copy">
          Tell us where you&apos;re interviewing, paste the job requirements, and optionally add your CV.
          We&apos;ll prepare questions tailored to the role and interview.
        </p>
        <button className="button button-primary" onClick={onStart} type="button">
          Prepare for an Interview <span aria-hidden="true">→</span>
        </button>
        <p className="home-note">No account required for this product preview.</p>
      </section>

      {recent ? (
        <section className="recent-section" aria-labelledby="recent-title">
          <div className="section-heading compact-heading">
            <div><p className="eyebrow">Recent</p><h2 id="recent-title">Continue preparing</h2></div>
          </div>
          <button className="recent-row" type="button" onClick={onOpen}>
            <span><strong>{recent.details.company}</strong><small>{recent.details.role}</small></span>
            <span><small>{recent.details.stage}</small><strong aria-hidden="true">→</strong></span>
          </button>
        </section>
      ) : (
        <section className="process-strip" aria-label="How interview preparation works">
          <div><span>01</span><p><strong>Add the interview details</strong><small>Company, role and vacancy requirements.</small></p></div>
          <div><span>02</span><p><strong>Review likely questions</strong><small>See what to prepare and why it matters.</small></p></div>
          <div><span>03</span><p><strong>Practice when you are ready</strong><small>Answer in a focused interview setting.</small></p></div>
        </section>
      )}
    </main>
  );
}

function InterviewForm({
  value,
  error,
  onChange,
  onSubmit,
}: {
  value: InterviewDetails;
  error: string | null;
  onChange: (value: InterviewDetails) => void;
  onSubmit: () => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const ready = value.company.trim().length > 1 && value.role.trim().length > 1 && value.jobDescription.trim().length >= 40;

  function update<K extends keyof InterviewDetails>(key: K, nextValue: InterviewDetails[K]) {
    onChange({ ...value, [key]: nextValue });
  }

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const extension = file.name.split(".").pop()?.toLocaleLowerCase("en-US");
    if (!extension || !["pdf", "docx"].includes(extension)) {
      setFileError("Please choose a PDF or DOCX file.");
      event.target.value = "";
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setFileError("The CV must be smaller than 10 MB.");
      event.target.value = "";
      return;
    }
    setFileError(null);
    update("cvFileName", file.name);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (ready) onSubmit();
  }

  return (
    <main className="page form-page">
      <div className="page-heading">
        <p className="eyebrow">New preparation</p>
        <h1>Tell us what interview you&apos;re preparing for.</h1>
        <p>Complete the details below. It should take no more than a few minutes.</p>
      </div>

      <form className="interview-form" onSubmit={submit}>
        <section className="form-section" aria-labelledby="role-details-heading">
          <div className="form-section-heading"><span>01</span><div><h2 id="role-details-heading">Role details</h2><p>Start with the company and position.</p></div></div>
          <div className="two-column-fields">
            <label>Company<input required autoComplete="organization" placeholder="PASHA Bank" value={value.company} onChange={(event) => update("company", event.target.value)} /></label>
            <label>Role / Position<input required placeholder="AI Engineer" value={value.role} onChange={(event) => update("role", event.target.value)} /></label>
          </div>
          <label className="full-field">Job posting link <span>Optional</span><input type="url" inputMode="url" placeholder="https://..." value={value.jobUrl} onChange={(event) => update("jobUrl", event.target.value)} /></label>
        </section>

        <section className="form-section" aria-labelledby="requirements-heading">
          <div className="form-section-heading"><span>02</span><div><h2 id="requirements-heading">Job requirements</h2><p>This is the strongest input for tailoring your questions.</p></div></div>
          <label className="full-field important-field">
            Job Description / Requirements
            <textarea required minLength={40} rows={9} placeholder="Paste the job description or vacancy requirements here..." value={value.jobDescription} onChange={(event) => update("jobDescription", event.target.value)} />
            <small>{value.jobDescription.length} characters · minimum 40</small>
          </label>
        </section>

        <section className="form-section" aria-labelledby="interview-details-heading">
          <div className="form-section-heading"><span>03</span><div><h2 id="interview-details-heading">Interview details</h2><p>Choose what you know. “Not sure” is completely fine.</p></div></div>
          <div className="three-column-fields">
            <label>Seniority <span>Optional</span><select value={value.seniority} onChange={(event) => update("seniority", event.target.value as Seniority)}>{seniorities.map((item) => <option key={item}>{item}</option>)}</select></label>
            <label>Interview stage<select value={value.stage} onChange={(event) => update("stage", event.target.value as InterviewStage)}>{stages.map((item) => <option key={item}>{item}</option>)}</select></label>
            <label>Interview language<select value={value.language} onChange={(event) => update("language", event.target.value as InterviewLanguage)}><option>English</option><option>Azerbaijani</option></select></label>
          </div>
        </section>

        <section className="form-section" aria-labelledby="cv-heading">
          <div className="form-section-heading"><span>04</span><div><h2 id="cv-heading">Add your CV <em>Optional</em></h2><p>Get questions based on the projects, technologies and claims in your CV.</p></div></div>
          {value.cvFileName ? (
            <div className="uploaded-file">
              <span className="file-type" aria-hidden="true">CV</span>
              <p><strong>{value.cvFileName}</strong><small>Ready to review</small></p>
              <button type="button" onClick={() => { update("cvFileName", null); if (fileInput.current) fileInput.current.value = ""; }}>Remove</button>
            </div>
          ) : (
            <label className="upload-field">
              <input ref={fileInput} type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={selectFile} />
              <strong>Drag and drop your CV, or <span>choose a file</span></strong>
              <small>PDF or DOCX · maximum 10 MB</small>
            </label>
          )}
          <p className="field-explanation">Adding your CV helps us prepare questions interviewers may ask about your projects, skills and experience.</p>
          {fileError ? <p className="form-error" role="alert">{fileError}</p> : null}
        </section>

        <div className="form-footer">
          <p>We use these details only to prepare this interview.</p>
          <button className="button button-primary" disabled={!ready} type="submit">Prepare Interview <span aria-hidden="true">→</span></button>
        </div>
        {error ? <p className="form-error submit-error" role="alert">{error}</p> : null}
      </form>
    </main>
  );
}

function Analyzing({ details, activeStep }: { details: InterviewDetails; activeStep: number }) {
  return (
    <main className="page analysis-page" aria-live="polite" aria-busy="true">
      <section className="analysis-panel">
        <p className="eyebrow">Preparing your interview</p>
        <h1>Building a focused preparation for {details.role}.</h1>
        <p className="analysis-context">{details.company} · {details.stage}</p>
        <ol className="analysis-steps">
          {analysisSteps.map((step, index) => (
            <li className={index < activeStep ? "complete" : index === activeStep ? "active" : ""} key={step}>
              <span aria-hidden="true">{index < activeStep ? "✓" : index + 1}</span>
              <p><strong>{step}</strong>{step === "Reviewing your CV" && !details.cvFileName ? <small>No CV added — continuing with role and vacancy evidence.</small> : null}</p>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}

function PreparationHeader({ analysis }: { analysis: InterviewAnalysis }) {
  return (
    <div className="preparation-header">
      <p className="eyebrow">Your interview preparation</p>
      <div><h1>{analysis.details.company}</h1><p>{analysis.details.role}<span aria-hidden="true">·</span>{analysis.details.stage}</p></div>
    </div>
  );
}

function CoverageNotice({ analysis }: { analysis: InterviewAnalysis }) {
  return (
    <section className="coverage-notice" aria-label="Company-specific data coverage">
      <div><p>Company-specific data</p><strong>{analysis.companyCoverage}</strong></div>
      <p>{analysis.companyCoverageNote}</p>
    </section>
  );
}

function Overview({ analysis, onQuestions, onPractice }: { analysis: InterviewAnalysis; onQuestions: () => void; onPractice: () => void }) {
  return (
    <main className="page prepared-page">
      <PreparationHeader analysis={analysis} />
      <CoverageNotice analysis={analysis} />

      <section className="focus-section" aria-labelledby="focus-heading">
        <div className="section-heading"><div><p className="eyebrow">Likely focus</p><h2 id="focus-heading">What this interview may explore</h2></div><p>Based on the role, vacancy requirements and available evidence.</p></div>
        <div className="focus-list">
          {analysis.focusAreas.map((area) => <div key={area.label}><span>{area.label}</span><strong>{area.priority}</strong></div>)}
        </div>
      </section>

      <section className="next-actions" aria-labelledby="choose-heading">
        <div className="section-heading"><div><p className="eyebrow">Choose how to prepare</p><h2 id="choose-heading">Your questions are ready</h2></div></div>
        <div className="action-options">
          <button type="button" onClick={onQuestions}><span>01</span><p><strong>View Questions</strong><small>Review likely questions and why each one matters. You do not need to answer.</small></p><b aria-hidden="true">→</b></button>
          <button type="button" onClick={onPractice}><span>02</span><p><strong>Practice Interview</strong><small>Answer selected questions and receive realistic follow-ups.</small></p><b aria-hidden="true">→</b></button>
        </div>
      </section>
    </main>
  );
}

function QuestionRow({ question, index, onPractice }: { question: PreparationQuestion; index: number; onPractice: (questionId: string) => void }) {
  const [openPanel, setOpenPanel] = useState<"reason" | "approach" | null>(null);
  return (
    <article className="question-row">
      <span className="question-number">{String(index + 1).padStart(2, "0")}</span>
      <div className="question-content">
        <h3>{question.question}</h3>
        <p className="source-line">{question.sources.join(" · ")}</p>
        <div className="question-actions">
          <button type="button" aria-expanded={openPanel === "reason"} onClick={() => setOpenPanel(openPanel === "reason" ? null : "reason")}>Why this question?</button>
          <button type="button" aria-expanded={openPanel === "approach"} onClick={() => setOpenPanel(openPanel === "approach" ? null : "approach")}>How should I approach this?</button>
          <button className="practice-link" type="button" onClick={() => onPractice(question.id)}>Practice <span aria-hidden="true">→</span></button>
        </div>
        {openPanel === "reason" ? <div className="question-detail"><strong>Why it matters</strong><p>{question.reason}</p></div> : null}
        {openPanel === "approach" ? <div className="question-detail"><strong>A strong answer should cover</strong><ul>{question.approach.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
      </div>
    </article>
  );
}

function Questions({ analysis, onPractice }: { analysis: InterviewAnalysis; onPractice: (questionId?: string) => void }) {
  const categories = useMemo(() => Array.from(new Set(analysis.questions.map((question) => question.category))), [analysis.questions]);
  const [category, setCategory] = useState<"All questions" | QuestionCategory>("All questions");
  const displayed = category === "All questions" ? analysis.questions : analysis.questions.filter((question) => question.category === category);
  return (
    <main className="page prepared-page questions-page">
      <PreparationHeader analysis={analysis} />
      <div className="section-heading question-heading"><div><p className="eyebrow">Preparation sheet</p><h2>Likely Interview Questions</h2></div><p>Selected from the role, job requirements, your CV and available interview signals.</p></div>

      {analysis.cvAreas.length ? (
        <section className="cv-insight" aria-labelledby="cv-insight-heading">
          <div><p className="eyebrow">CV review</p><h2 id="cv-insight-heading">CV areas likely to be explored</h2></div>
          <div>{analysis.cvAreas.map((area) => <p key={area.label}><span>{area.label}</span><strong>{area.priority}</strong></p>)}</div>
        </section>
      ) : (
        <section className="cv-unavailable"><strong>No CV added</strong><p>Your questions are based on the vacancy, role, industry and interview stage. You can start a new preparation to add a CV.</p></section>
      )}

      <div className="question-filters" role="group" aria-label="Filter questions by category">
        {(["All questions", ...categories] as const).map((item) => <button className={category === item ? "active" : ""} key={item} onClick={() => setCategory(item)} type="button">{item}</button>)}
      </div>
      <section className="question-list" aria-label="Likely interview questions">
        {displayed.map((question) => <QuestionRow key={question.id} question={question} index={analysis.questions.indexOf(question)} onPractice={onPractice} />)}
      </section>
    </main>
  );
}

function ChoiceGroup<T extends string>({ label, options, value, onChange }: { label: string; options: T[]; value: T; onChange: (value: T) => void }) {
  return (
    <fieldset className="choice-group"><legend>{label}</legend><div>{options.map((option) => <button aria-pressed={value === option} className={value === option ? "selected" : ""} key={option} type="button" onClick={() => onChange(option)}>{option}</button>)}</div></fieldset>
  );
}

function PracticeSetup({ analysis, onStart }: { analysis: InterviewAnalysis; onStart: (mode: PracticeMode, focus: PracticeFocus, duration: Duration) => void }) {
  const [mode, setMode] = useState<PracticeMode>("Practice");
  const [focus, setFocus] = useState<PracticeFocus>("Full Interview");
  const [duration, setDuration] = useState<Duration>("30 min");
  return (
    <main className="page prepared-page practice-setup-page">
      <PreparationHeader analysis={analysis} />
      <div className="page-heading short-heading"><p className="eyebrow">Practice interview</p><h2>Choose how you want to practise.</h2><p>Answer questions selected specifically for this interview and receive relevant follow-ups.</p></div>
      <section className="practice-options">
        <fieldset className="mode-choice"><legend>Choose mode</legend><div>
          <button aria-pressed={mode === "Real Interview"} className={mode === "Real Interview" ? "selected" : ""} onClick={() => setMode("Real Interview")} type="button"><strong>Real Interview</strong><small>Feedback is provided at the end.</small></button>
          <button aria-pressed={mode === "Practice"} className={mode === "Practice" ? "selected" : ""} onClick={() => setMode("Practice")} type="button"><strong>Practice</strong><small>Receive feedback while practising.</small></button>
        </div></fieldset>
        <ChoiceGroup label="Focus" options={["Full Interview", "Technical", "HR / Behavioral", "CV Deep Dive"]} value={focus} onChange={setFocus} />
        <ChoiceGroup label="Duration" options={["15 min", "30 min", "45 min"]} value={duration} onChange={setDuration} />
        <div className="practice-start"><p>{analysis.questions.length} tailored questions available</p><button className="button button-primary" onClick={() => onStart(mode, focus, duration)} type="button">Start Interview <span aria-hidden="true">→</span></button></div>
      </section>
    </main>
  );
}

function PracticeActive({
  analysis,
  mode,
  questions,
  initialQuestionId,
  onFinish,
}: {
  analysis: InterviewAnalysis;
  mode: PracticeMode;
  questions: PreparationQuestion[];
  initialQuestionId: string | null;
  onFinish: (completed: number) => void;
}) {
  const initialIndex = Math.max(0, initialQuestionId ? questions.findIndex((question) => question.id === initialQuestionId) : 0);
  const [index, setIndex] = useState(initialIndex);
  const [answer, setAnswer] = useState("");
  const [followUp, setFollowUp] = useState(false);
  const [feedback, setFeedback] = useState(false);
  const current = questions[index];
  const completed = index + (followUp ? 1 : 0);

  function advance() {
    if (!followUp && current.followUp) {
      setFollowUp(true);
    } else if (index >= questions.length - 1) {
      onFinish(questions.length);
      return;
    } else {
      setIndex((value) => value + 1);
      setFollowUp(false);
    }
    setAnswer("");
    setFeedback(false);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (answer.trim().length < 30) return;
    if (mode === "Practice") setFeedback(true);
    else advance();
  }

  return (
    <main className="page active-interview-page">
      <div className="active-context"><button type="button" onClick={() => onFinish(completed)}>End Interview</button><p><strong>{analysis.details.company} · {analysis.details.role}</strong><span>{analysis.details.stage} · {mode}</span></p><p>Question {index + 1} of {questions.length}</p></div>
      <div className="interview-progress" aria-label={`Question ${index + 1} of ${questions.length}`}><span style={{ width: `${((index + 1) / questions.length) * 100}%` }} /></div>
      <section className="interview-question" aria-live="polite">
        <p className="interviewer-label">Interviewer</p>
        <h1>{followUp ? current.followUp : current.question}</h1>
        {!followUp ? <p className="source-line">Selected from {current.sources.join(" · ")}</p> : <p className="source-line">Follow-up based on this topic</p>}
      </section>
      <form className="answer-form" onSubmit={submit}>
        <label htmlFor="candidate-answer">Your answer</label>
        <textarea id="candidate-answer" maxLength={2500} rows={8} autoFocus placeholder="Write your answer as you would say it in the interview..." value={answer} onChange={(event) => setAnswer(event.target.value)} disabled={feedback} />
        <div className="answer-footer"><span>{answer.length} / 2,500</span><button className="button button-primary" disabled={answer.trim().length < 30 || feedback} type="submit">Submit Answer</button></div>
      </form>
      {feedback ? (
        <section className="inline-feedback" aria-live="polite">
          <div><p className="eyebrow">Practice feedback</p><h2>Strengthen the evidence in your answer.</h2></div>
          <div className="feedback-columns"><div><strong>Strong points</strong><ul><li>You gave enough context to follow your reasoning.</li><li>Your answer addressed the core question directly.</li></ul></div><div><strong>Improve</strong><ul><li>Make your personal contribution explicit.</li><li>Add one measurable result or decision criterion.</li></ul></div></div>
          <div className="likely-follow-up"><span>Likely follow-up</span><p>“{current.followUp}”</p></div>
          <button className="button button-primary" type="button" onClick={advance}>Continue <span aria-hidden="true">→</span></button>
        </section>
      ) : null}
    </main>
  );
}

function Report({ analysis, mode, completed, onQuestions, onRestart }: { analysis: InterviewAnalysis; mode: PracticeMode; completed: number; onQuestions: () => void; onRestart: () => void }) {
  return (
    <main className="page prepared-page report-page">
      <PreparationHeader analysis={analysis} />
      <section className="report-intro"><p className="eyebrow">Interview complete</p><h2>Your preparation has a clear next step.</h2><p>You completed {completed} question{completed === 1 ? "" : "s"} in {mode.toLocaleLowerCase("en-US")} mode. Review the evidence behind each answer before your real interview.</p></section>
      <div className="report-grid">
        <section><p className="eyebrow">What worked</p><h3>Keep doing this</h3><ul><li>Address the question before adding background.</li><li>Explain the reasoning behind technical choices.</li><li>Connect your experience to the target role.</li></ul></section>
        <section><p className="eyebrow">Improve next</p><h3>Make each answer more credible</h3><ul><li>Quantify outcomes wherever possible.</li><li>Compare at least one realistic alternative.</li><li>Clarify what you personally owned.</li></ul></section>
      </div>
      <section className="recommended-next"><div><span>Recommended next step</span><strong>Review the likely questions and prepare two measurable examples.</strong></div><button className="button button-secondary" onClick={onQuestions} type="button">View Questions</button><button className="button button-primary" onClick={onRestart} type="button">Practice Again</button></section>
    </main>
  );
}

export default function HomePage() {
  const [view, setView] = useState<View>("home");
  const [details, setDetails] = useState<InterviewDetails>(initialDetails);
  const [analysis, setAnalysis] = useState<InterviewAnalysis | null>(null);
  const [analysisStep, setAnalysisStep] = useState(0);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [practiceMode, setPracticeMode] = useState<PracticeMode>("Practice");
  const [practiceQuestions, setPracticeQuestions] = useState<PreparationQuestion[]>([]);
  const [initialQuestionId, setInitialQuestionId] = useState<string | null>(null);
  const [completedQuestions, setCompletedQuestions] = useState(0);

  async function analyze() {
    setAnalysisError(null);
    setAnalysisStep(0);
    setView("analyzing");
    try {
      const result = await prepareInterview({ ...details, company: details.company.trim(), role: details.role.trim(), jobDescription: details.jobDescription.trim(), jobUrl: details.jobUrl.trim() }, setAnalysisStep);
      setAnalysis(result);
      setView("overview");
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : "We could not prepare this interview. Please try again.");
      setView("form");
    }
  }

  function beginPractice(mode: PracticeMode, focus: PracticeFocus, _duration: Duration, questionId: string | null = null) {
    if (!analysis) return;
    let selected = analysis.questions;
    if (focus === "Technical") selected = selected.filter((question) => ["Technical Questions", "System Design"].includes(question.category));
    if (focus === "HR / Behavioral") selected = selected.filter((question) => question.category === "HR / Recruiter");
    if (focus === "CV Deep Dive") selected = selected.filter((question) => question.category === "CV Questions");
    if (!selected.length) selected = analysis.questions;
    setPracticeMode(mode);
    setPracticeQuestions(selected);
    setInitialQuestionId(questionId);
    setView("practice-active");
  }

  function practiceOne(questionId?: string) {
    beginPractice("Practice", "Full Interview", "15 min", questionId ?? null);
  }

  function finishPractice(completed: number) {
    setCompletedQuestions(completed);
    setView("report");
  }

  return (
    <>
      <Header analysis={analysis} activeView={view} onNavigate={setView} />
      {view === "home" ? <Home recent={analysis} onStart={() => setView("form")} onOpen={() => setView("overview")} /> : null}
      {view === "form" ? <InterviewForm value={details} error={analysisError} onChange={setDetails} onSubmit={analyze} /> : null}
      {view === "analyzing" ? <Analyzing details={details} activeStep={analysisStep} /> : null}
      {view === "overview" && analysis ? <Overview analysis={analysis} onQuestions={() => setView("questions")} onPractice={() => setView("practice-setup")} /> : null}
      {view === "questions" && analysis ? <Questions analysis={analysis} onPractice={practiceOne} /> : null}
      {view === "practice-setup" && analysis ? <PracticeSetup analysis={analysis} onStart={beginPractice} /> : null}
      {view === "practice-active" && analysis ? <PracticeActive key={`${analysis.id}-${initialQuestionId}-${practiceMode}`} analysis={analysis} mode={practiceMode} questions={practiceQuestions.length ? practiceQuestions : analysis.questions} initialQuestionId={initialQuestionId} onFinish={finishPractice} /> : null}
      {view === "report" && analysis ? <Report analysis={analysis} mode={practiceMode} completed={completedQuestions} onQuestions={() => setView("questions")} onRestart={() => setView("practice-setup")} /> : null}
    </>
  );
}
