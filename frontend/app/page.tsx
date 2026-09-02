"use client";

import { ChangeEvent, createContext, FormEvent, useContext, useEffect, useMemo, useRef, useState } from "react";

import {
  InterviewAnalysis,
  InterviewDetails,
  InterviewLanguage,
  InterviewStage,
  PreparationQuestion,
  prepareInterview,
  QuestionCategory,
  Seniority,
} from "../lib/interview-api";
import { UiCopy, UiLanguage, uiCopy } from "../lib/ui-copy";

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

type InterfaceLanguageContextValue = {
  language: UiLanguage;
  setLanguage: (language: UiLanguage) => void;
  t: UiCopy;
};

const InterfaceLanguageContext = createContext<InterfaceLanguageContextValue | null>(null);

function useInterfaceLanguage() {
  const value = useContext(InterfaceLanguageContext);
  if (!value) throw new Error("Interface language context is unavailable");
  return value;
}

function localizeFocusArea(label: string, t: UiCopy) {
  const labels: Record<string, string> = {
    "RAG / LLM systems": t.focusAreaLabels.rag,
    "Python and API engineering": t.focusAreaLabels.python,
    "Production deployment": t.focusAreaLabels.deployment,
    "Technical decision-making": t.focusAreaLabels.decisions,
    "Clear evidence and outcomes": t.focusAreaLabels.evidence,
    "Project ownership": t.focusAreaLabels.ownership,
    "Technical decisions": t.focusAreaLabels.technicalDecisions,
    "Measured outcomes": t.focusAreaLabels.outcomes,
  };
  return labels[label] ?? label;
}

const initialDetails: InterviewDetails = {
  company: "",
  role: "",
  jobDescription: "",
  jobUrl: "",
  seniority: "Not specified",
  stage: "Not sure",
  language: "English",
  cvFileName: null,
  cvFileType: null,
  cvFileData: null,
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
  const { t } = useInterfaceLanguage();
  return (
    <button className="brand" type="button" onClick={onClick} aria-label={t.brandAria}>
      <span aria-hidden="true">IP</span>
      <b>Interview Prep</b>
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
  const { language, setLanguage, t } = useInterfaceLanguage();
  const preparedView = ["overview", "questions", "practice-setup", "practice-active", "report"].includes(activeView);
  return (
    <header className="site-header">
      <div className="header-inner">
        <Brand onClick={() => onNavigate("home")} />
        {analysis && preparedView ? (
          <nav className="preparation-nav" aria-label={t.nav.label}>
            <button className={activeView === "overview" ? "active" : ""} onClick={() => onNavigate("overview")} type="button">{t.nav.overview}</button>
            <button className={activeView === "questions" ? "active" : ""} onClick={() => onNavigate("questions")} type="button">{t.nav.questions}</button>
            <button className={activeView.startsWith("practice") ? "active" : ""} onClick={() => onNavigate("practice-setup")} type="button">{t.nav.practice}</button>
          </nav>
        ) : null}
        <div className="language-switch" role="group" aria-label={t.switchLanguage}>
          <button aria-pressed={language === "az"} className={language === "az" ? "active" : ""} onClick={() => setLanguage("az")} type="button">AZ</button>
          <span aria-hidden="true">/</span>
          <button aria-pressed={language === "en"} className={language === "en" ? "active" : ""} onClick={() => setLanguage("en")} type="button">EN</button>
        </div>
        <button className="header-action" data-short-label={language === "az" ? "Yeni" : "New"} type="button" onClick={() => onNavigate("form")}><span>{t.nav.newPreparation}</span></button>
      </div>
    </header>
  );
}

function Home({ recent, onStart, onOpen }: { recent: InterviewAnalysis | null; onStart: () => void; onOpen: () => void }) {
  const { t } = useInterfaceLanguage();
  return (
    <>
      <main className="page home-page">
        <section className="home-hero" aria-labelledby="home-title">
          <div className="home-intro">
            <p className="eyebrow">{t.home.eyebrow}</p>
            <h1 id="home-title">{t.home.title}</h1>
            <p className="home-copy">{t.home.intro}</p>
            <button className="button button-primary" onClick={onStart} type="button">
              {t.home.cta} <span aria-hidden="true">→</span>
            </button>
            <p className="home-note">{t.home.noAccount}</p>
          </div>

          <aside className="product-preview" aria-label={t.home.previewAria}>
            <div className="preview-header">
              <div>
                <p>{t.home.previewLabel}</p>
                <h2>{t.home.previewCompany}</h2>
                <span>{t.home.previewRole}</span>
              </div>
              <strong>{t.home.previewStage}</strong>
            </div>

            <section className="preview-section" aria-labelledby="preview-sources-title">
              <h3 id="preview-sources-title">{t.home.sources}</h3>
              <dl className="preview-rows">
                <div><dt>{t.home.jobRequirements}</dt><dd>{t.home.included}</dd></div>
                <div><dt>CV</dt><dd>{t.home.included}</dd></div>
                <div><dt>{t.home.companySignals}</dt><dd>{t.home.available}</dd></div>
              </dl>
            </section>

            <section className="preview-section" aria-labelledby="preview-focus-title">
              <h3 id="preview-focus-title">{t.home.focusAreas}</h3>
              <dl className="preview-rows">
                <div><dt>{t.home.rag}</dt><dd>{t.home.high}</dd></div>
                <div><dt>{t.home.python}</dt><dd>{t.home.high}</dd></div>
                <div><dt>{t.home.ml}</dt><dd>{t.home.high}</dd></div>
                <div><dt>{t.home.deployment}</dt><dd>{t.home.medium}</dd></div>
              </dl>
            </section>

            <section className="preview-question" aria-labelledby="preview-question-title">
              <div><strong>{t.home.questionCount}</strong><span>{t.home.exampleQuestionLabel}</span></div>
              <p id="preview-question-title">{t.home.exampleQuestion}</p>
              <span className="source-tag">{t.home.jobDescription}</span>
            </section>
          </aside>
        </section>

        <section className="home-benefits" aria-labelledby="benefits-title">
          <div className="home-section-heading">
            <div><p className="eyebrow">{t.home.onePreparation}</p><h2 id="benefits-title">{t.home.benefitsTitle}</h2></div>
            <p>{t.home.benefitsIntro}</p>
          </div>
          <div className="benefit-grid">
            {t.home.benefits.map(([title, description], index) => (
              <article key={title}><span>{String(index + 1).padStart(2, "0")}</span><h3>{title}</h3><p>{description}</p></article>
            ))}
          </div>
        </section>

        <section className="personalization-section" aria-labelledby="personalization-title">
          <div className="home-section-heading">
            <div><p className="eyebrow">{t.home.personalised}</p><h2 id="personalization-title">{t.home.personalisedTitle}</h2></div>
            <p>{t.home.personalisedIntro}</p>
          </div>
          <div className="personalization-example">
            <div className="signal-column">
              <div className="signal-group">
                <h3>{t.home.vacancyTitle}</h3>
                <ul>{t.home.vacancySignals.map((signal) => <li key={signal}>{signal}</li>)}</ul>
              </div>
              <div className="signal-group">
                <h3>{t.home.cvSignalsTitle}</h3>
                <ul>{t.home.cvSignals.map((signal) => <li key={signal}>{signal}</li>)}</ul>
              </div>
            </div>
            <div className="example-flow" aria-hidden="true"><span>→</span></div>
            <div className="resulting-questions">
              <h3>{t.home.likelyQuestions}</h3>
              <ol>{t.home.sampleQuestions.map((question) => <li key={question}>{question}</li>)}</ol>
            </div>
          </div>
        </section>

        {recent ? (
          <section className="recent-section" aria-labelledby="recent-title">
            <div className="section-heading compact-heading">
              <div><p className="eyebrow">{t.home.recent}</p><h2 id="recent-title">{t.home.continuePreparing}</h2></div>
            </div>
            <button className="recent-row" type="button" onClick={onOpen}>
              <span><strong>{recent.details.company}</strong><small>{recent.details.role}</small></span>
              <span><small>{t.stageLabels[recent.details.stage]}</small><strong aria-hidden="true">→</strong></span>
            </button>
          </section>
        ) : null}

        <section className="home-final-cta" aria-labelledby="home-cta-title">
          <div><p className="eyebrow">{t.home.ready}</p><h2 id="home-cta-title">{t.home.finalTitle}</h2><p>{t.home.finalIntro}</p></div>
          <button className="button button-primary" onClick={onStart} type="button">{t.home.start} <span aria-hidden="true">→</span></button>
        </section>
      </main>

      <footer className="home-footer">
        <div><strong>Interview Prep</strong><span>{t.home.footer}</span></div>
      </footer>
    </>
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
  const { t } = useInterfaceLanguage();
  const fileInput = useRef<HTMLInputElement>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const ready = value.company.trim().length > 1 && value.role.trim().length > 1 && value.jobDescription.trim().length >= 40;

  function update<K extends keyof InterviewDetails>(key: K, nextValue: InterviewDetails[K]) {
    onChange({ ...value, [key]: nextValue });
  }

  async function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const extension = file.name.split(".").pop()?.toLocaleLowerCase("en-US");
    if (!extension || !["pdf", "docx"].includes(extension)) {
      setFileError(t.form.invalidFile);
      event.target.value = "";
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setFileError(t.form.fileTooLarge);
      event.target.value = "";
      return;
    }
    setFileError(null);
    try {
      const cvFileData = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => typeof reader.result === "string" ? resolve(reader.result) : reject(new Error("invalid file data"));
        reader.onerror = () => reject(reader.error ?? new Error("file read failed"));
        reader.readAsDataURL(file);
      });
      onChange({ ...value, cvFileName: file.name, cvFileType: file.type, cvFileData });
    } catch {
      setFileError(t.form.fileReadError);
      event.target.value = "";
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (ready) onSubmit();
  }

  return (
    <main className="page form-page">
      <div className="page-heading">
        <p className="eyebrow">{t.form.eyebrow}</p>
        <h1>{t.form.title}</h1>
        <p>{t.form.intro}</p>
      </div>

      <form className="interview-form" onSubmit={submit}>
        <section className="form-section" aria-labelledby="role-details-heading">
          <div className="form-section-heading"><span>01</span><div><h2 id="role-details-heading">{t.form.roleTitle}</h2><p>{t.form.roleIntro}</p></div></div>
          <div className="two-column-fields">
            <label>{t.form.company}<input required autoComplete="organization" placeholder="PASHA Bank" value={value.company} onChange={(event) => update("company", event.target.value)} /></label>
            <label>{t.form.role}<input required placeholder="AI Engineer" value={value.role} onChange={(event) => update("role", event.target.value)} /></label>
          </div>
          <label className="full-field">{t.form.jobLink} <span>{t.form.optional}</span><input type="url" inputMode="url" placeholder="https://..." value={value.jobUrl} onChange={(event) => update("jobUrl", event.target.value)} /></label>
        </section>

        <section className="form-section" aria-labelledby="requirements-heading">
          <div className="form-section-heading"><span>02</span><div><h2 id="requirements-heading">{t.form.requirementsTitle}</h2><p>{t.form.requirementsIntro}</p></div></div>
          <label className="full-field important-field">
            {t.form.jobDescription}
            <textarea required minLength={40} rows={9} placeholder={t.form.jobPlaceholder} value={value.jobDescription} onChange={(event) => update("jobDescription", event.target.value)} />
            <small>{t.form.characters(value.jobDescription.length)}</small>
          </label>
        </section>

        <section className="form-section" aria-labelledby="interview-details-heading">
          <div className="form-section-heading"><span>03</span><div><h2 id="interview-details-heading">{t.form.interviewTitle}</h2><p>{t.form.interviewIntro}</p></div></div>
          <div className="three-column-fields">
            <label>{t.form.seniority} <span>{t.form.optional}</span><select value={value.seniority} onChange={(event) => update("seniority", event.target.value as Seniority)}>{seniorities.map((item) => <option key={item} value={item}>{t.seniorityLabels[item]}</option>)}</select></label>
            <label>{t.form.stage}<select value={value.stage} onChange={(event) => update("stage", event.target.value as InterviewStage)}>{stages.map((item) => <option key={item} value={item}>{t.stageLabels[item]}</option>)}</select></label>
            <label>{t.form.language}<select value={value.language} onChange={(event) => update("language", event.target.value as InterviewLanguage)}>{(["Azerbaijani", "English"] as InterviewLanguage[]).map((item) => <option key={item} value={item}>{t.interviewLanguageLabels[item]}</option>)}</select></label>
          </div>
        </section>

        <section className="form-section" aria-labelledby="cv-heading">
          <div className="form-section-heading"><span>04</span><div><h2 id="cv-heading">{t.form.cvTitle} <em>{t.form.optional}</em></h2><p>{t.form.cvIntro}</p></div></div>
          {value.cvFileName ? (
            <div className="uploaded-file">
              <span className="file-type" aria-hidden="true">CV</span>
              <p><strong>{value.cvFileName}</strong><small>{t.form.readyToReview}</small></p>
              <button type="button" onClick={() => { onChange({ ...value, cvFileName: null, cvFileType: null, cvFileData: null }); if (fileInput.current) fileInput.current.value = ""; }}>{t.form.remove}</button>
            </div>
          ) : (
            <label className="upload-field">
              <input ref={fileInput} type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={selectFile} />
              <strong>{t.form.uploadStart} <span>{t.form.chooseFile}</span></strong>
              <small>{t.form.uploadMeta}</small>
            </label>
          )}
          <p className="field-explanation">{t.form.cvExplanation}</p>
          {fileError ? <p className="form-error" role="alert">{fileError}</p> : null}
        </section>

        <div className="form-footer">
          <p>{t.form.privacy}</p>
          <button className="button button-primary" disabled={!ready} type="submit">{t.form.prepare} <span aria-hidden="true">→</span></button>
        </div>
        {error ? <p className="form-error submit-error" role="alert">{error}</p> : null}
      </form>
    </main>
  );
}

function Analyzing({ details, activeStep }: { details: InterviewDetails; activeStep: number }) {
  const { t } = useInterfaceLanguage();
  return (
    <main className="page analysis-page" aria-live="polite" aria-busy="true">
      <section className="analysis-panel">
        <p className="eyebrow">{t.analysis.eyebrow}</p>
        <h1>{t.analysis.title(details.role)}</h1>
        <p className="analysis-context">{details.company} · {t.stageLabels[details.stage]}</p>
        <ol className="analysis-steps">
          {t.analysis.steps.map((step, index) => (
            <li className={index < activeStep ? "complete" : index === activeStep ? "active" : ""} key={step}>
              <span aria-hidden="true">{index < activeStep ? "✓" : index + 1}</span>
              <p><strong>{step}</strong>{index === 2 && !details.cvFileName ? <small>{t.analysis.noCv}</small> : null}</p>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}

function PreparationHeader({ analysis }: { analysis: InterviewAnalysis }) {
  const { t } = useInterfaceLanguage();
  return (
    <div className="preparation-header">
      <p className="eyebrow">{t.preparation.eyebrow}</p>
      <div><h1>{analysis.details.company}</h1><p>{analysis.details.role}<span aria-hidden="true">·</span>{t.stageLabels[analysis.details.stage]}</p></div>
    </div>
  );
}

function CoverageNotice({ analysis }: { analysis: InterviewAnalysis }) {
  const { t } = useInterfaceLanguage();
  return (
    <>
      <section className="coverage-notice" aria-label={t.preparation.coverageAria}>
        <div>
          <p>{t.preparation.companyData}</p>
          <strong>{analysis.companyCoverage === "Strong" ? t.preparation.strong : t.preparation.limited}</strong>
          <span className={`analysis-mode ${analysis.analysisMode}`}>{analysis.analysisMode === "live_research" ? t.preparation.liveResearch : t.preparation.localPreview}</span>
        </div>
        <p>{analysis.analysisMode === "local_preview" ? t.preparation.previewNote : analysis.companyCoverage === "Strong" ? t.preparation.strongNote : t.preparation.limitedNote}</p>
      </section>
      {analysis.researchSources.length ? (
        <section className="research-sources" aria-labelledby="research-sources-title">
          <div><p className="eyebrow">{t.preparation.evidence}</p><h2 id="research-sources-title">{t.preparation.sourcesUsed(analysis.researchSources.length)}</h2></div>
          <div className="research-source-links">
            {analysis.researchSources.map((source) => <a href={source.url} key={source.id} target="_blank" rel="noreferrer"><span>{source.title}</span><small>{source.domain}</small></a>)}
          </div>
        </section>
      ) : null}
    </>
  );
}

function Overview({ analysis, onQuestions, onPractice }: { analysis: InterviewAnalysis; onQuestions: () => void; onPractice: () => void }) {
  const { t } = useInterfaceLanguage();
  return (
    <main className="page prepared-page">
      <PreparationHeader analysis={analysis} />
      <CoverageNotice analysis={analysis} />

      {analysis.companySignals.length ? (
        <section className="company-signal-section" aria-labelledby="company-signal-heading">
          <div>
            <p className="eyebrow">{t.preparation.companySignals}</p>
            <h2 id="company-signal-heading">{t.preparation.companySignalsTitle}</h2>
            <p>{t.preparation.companySignalsIntro}</p>
          </div>
          <ol>
            {analysis.companySignals.map((item, index) => (
              <li key={`${item.signal}-${index}`}>
                <p>{item.signal}</p>
                <div>
                  {item.evidence.map((source) => <a href={source.url} key={source.id} target="_blank" rel="noreferrer">{source.domain}</a>)}
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <section className="focus-section" aria-labelledby="focus-heading">
        <div className="section-heading"><div><p className="eyebrow">{t.preparation.likelyFocus}</p><h2 id="focus-heading">{t.preparation.explore}</h2></div><p>{t.preparation.focusIntro}</p></div>
        <div className="focus-list">
          {analysis.focusAreas.map((area) => <div key={area.label}><span>{localizeFocusArea(area.label, t)}</span><strong>{t.priorityLabels[area.priority]}</strong></div>)}
        </div>
      </section>

      <section className="next-actions" aria-labelledby="choose-heading">
        <div className="section-heading"><div><p className="eyebrow">{t.preparation.choose}</p><h2 id="choose-heading">{t.preparation.ready}</h2></div></div>
        <div className="action-options">
          <button type="button" onClick={onQuestions}><span>01</span><p><strong>{t.preparation.viewQuestions}</strong><small>{t.preparation.viewQuestionsIntro}</small></p><b aria-hidden="true">→</b></button>
          <button type="button" onClick={onPractice}><span>02</span><p><strong>{t.preparation.practiceInterview}</strong><small>{t.preparation.practiceIntro}</small></p><b aria-hidden="true">→</b></button>
        </div>
      </section>
    </main>
  );
}

function QuestionRow({ question, index, onPractice }: { question: PreparationQuestion; index: number; onPractice: (questionId: string) => void }) {
  const { t } = useInterfaceLanguage();
  const [openPanel, setOpenPanel] = useState<"reason" | "approach" | null>(null);
  return (
    <article className="question-row">
      <span className="question-number">{String(index + 1).padStart(2, "0")}</span>
      <div className="question-content">
        <h3>{question.question}</h3>
        <p className="source-line">{question.sources.map((source) => t.sourceLabels[source]).join(" · ")}<span>{t.specificityLabels[question.specificity]}</span></p>
        {question.evidence.length ? (
          <div className="question-evidence" aria-label={t.questions.evidence}>
            <span>{t.questions.evidence}</span>
            {question.evidence.map((source) => <a href={source.url} key={source.id} target="_blank" rel="noreferrer">{source.domain}</a>)}
          </div>
        ) : null}
        <div className="question-actions">
          <button type="button" aria-expanded={openPanel === "reason"} onClick={() => setOpenPanel(openPanel === "reason" ? null : "reason")}>{t.questions.why}</button>
          <button type="button" aria-expanded={openPanel === "approach"} onClick={() => setOpenPanel(openPanel === "approach" ? null : "approach")}>{t.questions.approach}</button>
          <button className="practice-link" type="button" onClick={() => onPractice(question.id)}>{t.questions.practice} <span aria-hidden="true">→</span></button>
        </div>
        {openPanel === "reason" ? <div className="question-detail"><strong>{t.questions.whyTitle}</strong><p>{question.reason}</p></div> : null}
        {openPanel === "approach" ? <div className="question-detail"><strong>{t.questions.approachTitle}</strong><ul>{question.approach.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
      </div>
    </article>
  );
}

function Questions({ analysis, onPractice }: { analysis: InterviewAnalysis; onPractice: (questionId?: string) => void }) {
  const { t } = useInterfaceLanguage();
  const categories = useMemo(() => Array.from(new Set(analysis.questions.map((question) => question.category))), [analysis.questions]);
  const [category, setCategory] = useState<"All questions" | QuestionCategory>("All questions");
  const displayed = category === "All questions" ? analysis.questions : analysis.questions.filter((question) => question.category === category);
  return (
    <main className="page prepared-page questions-page">
      <PreparationHeader analysis={analysis} />
      <div className="section-heading question-heading"><div><p className="eyebrow">{t.questions.sheet}</p><h2>{t.questions.title}</h2></div><p>{t.questions.intro}</p></div>

      {analysis.cvAreas.length ? (
        <section className="cv-insight" aria-labelledby="cv-insight-heading">
          <div><p className="eyebrow">{t.questions.cvReview}</p><h2 id="cv-insight-heading">{t.questions.cvAreas}</h2></div>
          <div>{analysis.cvAreas.map((area) => <p key={area.label}><span>{localizeFocusArea(area.label, t)}</span><strong>{t.priorityLabels[area.priority]}</strong></p>)}</div>
        </section>
      ) : (
        <section className="cv-unavailable"><strong>{t.questions.noCv}</strong><p>{t.questions.noCvIntro}</p></section>
      )}

      <div className="question-filters" role="group" aria-label={t.questions.filterAria}>
        {(["All questions", ...categories] as const).map((item) => <button className={category === item ? "active" : ""} key={item} onClick={() => setCategory(item)} type="button">{item === "All questions" ? t.questions.all : t.categoryLabels[item]}</button>)}
      </div>
      <section className="question-list" aria-label={t.questions.listAria}>
        {displayed.map((question) => <QuestionRow key={question.id} question={question} index={analysis.questions.indexOf(question)} onPractice={onPractice} />)}
      </section>
    </main>
  );
}

function ChoiceGroup<T extends string>({ label, options, value, onChange, getLabel = (option) => option }: { label: string; options: T[]; value: T; onChange: (value: T) => void; getLabel?: (option: T) => string }) {
  return (
    <fieldset className="choice-group"><legend>{label}</legend><div>{options.map((option) => <button aria-pressed={value === option} className={value === option ? "selected" : ""} key={option} type="button" onClick={() => onChange(option)}>{getLabel(option)}</button>)}</div></fieldset>
  );
}

function PracticeSetup({ analysis, onStart }: { analysis: InterviewAnalysis; onStart: (mode: PracticeMode, focus: PracticeFocus, duration: Duration) => void }) {
  const { t } = useInterfaceLanguage();
  const [mode, setMode] = useState<PracticeMode>("Practice");
  const [focus, setFocus] = useState<PracticeFocus>("Full Interview");
  const [duration, setDuration] = useState<Duration>("30 min");
  return (
    <main className="page prepared-page practice-setup-page">
      <PreparationHeader analysis={analysis} />
      <div className="page-heading short-heading"><p className="eyebrow">{t.practice.eyebrow}</p><h2>{t.practice.title}</h2><p>{t.practice.intro}</p></div>
      <section className="practice-options">
        <fieldset className="mode-choice"><legend>{t.practice.chooseMode}</legend><div>
          <button aria-pressed={mode === "Real Interview"} className={mode === "Real Interview" ? "selected" : ""} onClick={() => setMode("Real Interview")} type="button"><strong>{t.practice.real}</strong><small>{t.practice.realIntro}</small></button>
          <button aria-pressed={mode === "Practice"} className={mode === "Practice" ? "selected" : ""} onClick={() => setMode("Practice")} type="button"><strong>{t.practice.practice}</strong><small>{t.practice.practiceIntro}</small></button>
        </div></fieldset>
        <ChoiceGroup label={t.practice.focus} options={["Full Interview", "Technical", "HR / Behavioral", "CV Deep Dive"]} value={focus} onChange={setFocus} getLabel={(option) => t.practice.focusLabels[option]} />
        <ChoiceGroup label={t.practice.duration} options={["15 min", "30 min", "45 min"]} value={duration} onChange={setDuration} />
        <div className="practice-start"><p>{t.practice.questionCount(analysis.questions.length)}</p><button className="button button-primary" onClick={() => onStart(mode, focus, duration)} type="button">{t.practice.start} <span aria-hidden="true">→</span></button></div>
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
  const { t } = useInterfaceLanguage();
  const requestedIndex = initialQuestionId ? questions.findIndex((question) => question.id === initialQuestionId) : 0;
  const initialIndex = Math.max(0, requestedIndex);
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
      <div className="active-context"><button type="button" onClick={() => onFinish(completed)}>{t.active.end}</button><p><strong>{analysis.details.company} · {analysis.details.role}</strong><span>{t.stageLabels[analysis.details.stage]} · {t.practice.modeLabels[mode]}</span></p><p>{t.active.questionProgress(index + 1, questions.length)}</p></div>
      <div className="interview-progress" aria-label={t.active.questionProgress(index + 1, questions.length)}><span style={{ width: `${((index + 1) / questions.length) * 100}%` }} /></div>
      <section className="interview-question" aria-live="polite">
        <p className="interviewer-label">{t.active.interviewer}</p>
        <h1>{followUp ? current.followUp : current.question}</h1>
        {!followUp ? <p className="source-line">{t.active.selectedFrom}: {current.sources.map((source) => t.sourceLabels[source]).join(" · ")}</p> : <p className="source-line">{t.active.followUpTopic}</p>}
      </section>
      <form className="answer-form" onSubmit={submit}>
        <label htmlFor="candidate-answer">{t.active.answer}</label>
        <textarea id="candidate-answer" maxLength={2500} rows={8} autoFocus placeholder={t.active.placeholder} value={answer} onChange={(event) => setAnswer(event.target.value)} disabled={feedback} />
        <div className="answer-footer"><span>{answer.length} / 2,500</span><button className="button button-primary" disabled={answer.trim().length < 30 || feedback} type="submit">{t.active.submit}</button></div>
      </form>
      {feedback ? (
        <section className="inline-feedback" aria-live="polite">
          <div><p className="eyebrow">{t.active.feedback}</p><h2>{t.active.feedbackTitle}</h2></div>
          <div className="feedback-columns"><div><strong>{t.active.strongPoints}</strong><ul>{t.active.strongItems.map((item) => <li key={item}>{item}</li>)}</ul></div><div><strong>{t.active.improve}</strong><ul>{t.active.improveItems.map((item) => <li key={item}>{item}</li>)}</ul></div></div>
          <div className="likely-follow-up"><span>{t.active.likelyFollowUp}</span><p>“{current.followUp}”</p></div>
          <button className="button button-primary" type="button" onClick={advance}>{t.active.continue} <span aria-hidden="true">→</span></button>
        </section>
      ) : null}
    </main>
  );
}

function Report({ analysis, mode, completed, onQuestions, onRestart }: { analysis: InterviewAnalysis; mode: PracticeMode; completed: number; onQuestions: () => void; onRestart: () => void }) {
  const { t } = useInterfaceLanguage();
  return (
    <main className="page prepared-page report-page">
      <PreparationHeader analysis={analysis} />
      <section className="report-intro"><p className="eyebrow">{t.report.complete}</p><h2>{t.report.title}</h2><p>{t.report.summary(completed, t.practice.modeLabels[mode])}</p></section>
      <div className="report-grid">
        <section><p className="eyebrow">{t.report.worked}</p><h3>{t.report.keep}</h3><ul>{t.report.workedItems.map((item) => <li key={item}>{item}</li>)}</ul></section>
        <section><p className="eyebrow">{t.report.improve}</p><h3>{t.report.credible}</h3><ul>{t.report.improveItems.map((item) => <li key={item}>{item}</li>)}</ul></section>
      </div>
      <section className="recommended-next"><div><span>{t.report.next}</span><strong>{t.report.recommendation}</strong></div><button className="button button-secondary" onClick={onQuestions} type="button">{t.report.viewQuestions}</button><button className="button button-primary" onClick={onRestart} type="button">{t.report.practiceAgain}</button></section>
    </main>
  );
}

export default function HomePage() {
  const [uiLanguage, setUiLanguage] = useState<UiLanguage>("en");
  const [view, setView] = useState<View>("home");
  const [details, setDetails] = useState<InterviewDetails>(initialDetails);
  const [analysis, setAnalysis] = useState<InterviewAnalysis | null>(null);
  const [analysisStep, setAnalysisStep] = useState(0);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [practiceMode, setPracticeMode] = useState<PracticeMode>("Practice");
  const [practiceQuestions, setPracticeQuestions] = useState<PreparationQuestion[]>([]);
  const [initialQuestionId, setInitialQuestionId] = useState<string | null>(null);
  const [completedQuestions, setCompletedQuestions] = useState(0);
  const t = uiCopy[uiLanguage];

  useEffect(() => {
    document.documentElement.lang = uiLanguage;
  }, [uiLanguage]);

  function changeUiLanguage(language: UiLanguage) {
    setUiLanguage(language);
  }

  async function analyze() {
    setAnalysisError(null);
    setAnalysisStep(0);
    setView("analyzing");
    try {
      const result = await prepareInterview({ ...details, company: details.company.trim(), role: details.role.trim(), jobDescription: details.jobDescription.trim(), jobUrl: details.jobUrl.trim() }, setAnalysisStep);
      setAnalysis(result);
      setView("overview");
    } catch {
      setAnalysisError(t.form.prepareError);
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
    <InterfaceLanguageContext.Provider value={{ language: uiLanguage, setLanguage: changeUiLanguage, t }}>
      <Header analysis={analysis} activeView={view} onNavigate={setView} />
      {view === "home" ? <Home recent={analysis} onStart={() => setView("form")} onOpen={() => setView("overview")} /> : null}
      {view === "form" ? <InterviewForm value={details} error={analysisError} onChange={setDetails} onSubmit={analyze} /> : null}
      {view === "analyzing" ? <Analyzing details={details} activeStep={analysisStep} /> : null}
      {view === "overview" && analysis ? <Overview analysis={analysis} onQuestions={() => setView("questions")} onPractice={() => setView("practice-setup")} /> : null}
      {view === "questions" && analysis ? <Questions analysis={analysis} onPractice={practiceOne} /> : null}
      {view === "practice-setup" && analysis ? <PracticeSetup analysis={analysis} onStart={beginPractice} /> : null}
      {view === "practice-active" && analysis ? <PracticeActive key={`${analysis.id}-${initialQuestionId}-${practiceMode}`} analysis={analysis} mode={practiceMode} questions={practiceQuestions.length ? practiceQuestions : analysis.questions} initialQuestionId={initialQuestionId} onFinish={finishPractice} /> : null}
      {view === "report" && analysis ? <Report analysis={analysis} mode={practiceMode} completed={completedQuestions} onQuestions={() => setView("questions")} onRestart={() => setView("practice-setup")} /> : null}
    </InterfaceLanguageContext.Provider>
  );
}
