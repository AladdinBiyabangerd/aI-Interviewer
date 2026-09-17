"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { availableTopics, defaultTopics, levels, roadmapUrl, topics, type AnswerFeedback, type AssessmentView, type Level, type PublicQuestion, type Reference } from "../../lib/assessment";
import { highlightJava } from "../../lib/java-syntax";
import { Brand } from "../brand";
import { PortalAccountChip } from "../portal-account-chip";
import "../assessment.css";

type Language = "az" | "en";
const translate = (language: Language, az: string, en: string) => language === "az" ? az : en;

const topicNames: Record<string, string> = {
  "core-java": "Java əsasları və OOP", collections: "Kolleksiyalar və istisnalar",
  spring: "Spring və REST", data: "SQL və verilənlərin saxlanması",
  testing: "Testləşdirmə və məsuliyyətli AI", tools: "Git, Linux və build alətləri",
  security: "API təhlükəsizliyi", delivery: "Konteynerlər və CI/CD",
  ai: "LLM, RAG və alətlər", observability: "Müşahidə və monitorinq",
  concurrency: "Java paralelliyi", distributed: "Paylanmış sistemlər və Kafka",
  performance: "JVM, keş və performans", operations: "Kubernetes və dayanıqlılıq",
  agents: "AI agentləri və qiymətləndirmə",
};
const levelNames: Record<Level, string> = { Junior: "Başlanğıc", Mid: "Orta", Senior: "İrəli" };
const errorMessages: Record<string, [string, string]> = {
  topic_unavailable: ["Bu mövzuda yayımlanmış sual yoxdur. Başqa mövzu seçin.", "One of these topics has no published questions yet. Choose another topic."],
  book_unavailable: ["Kitab üzrə məşq hələ hazır deyil. Ümumi testi seçin.", "Book practice is not ready yet. Try the general assessment."],
  assessment_unavailable: ["Test müvəqqəti əlçatmazdır. Bir az sonra yenidən cəhd edin.", "Assessments are temporarily unavailable. Please try again."],
  rate_limited: ["Qısa müddətdə çox test başladınız. Bir neçə dəqiqə gözləyin.", "You have started several assessments recently. Please wait a few minutes."],
  session_not_found: ["Bu sessiyanın müddəti bitib və ya başqa brauzerə aiddir. Yeni test başladın.", "This assessment has expired or belongs to another browser. Start a new assessment."],
  stale_question: ["Sual başqa tabda dəyişib. Saxlanmış testi yeniləyin.", "This question advanced in another tab. Reload the saved assessment."],
  cannot_go_back: ["Bu sualdan geri qayıtmaq mümkün deyil.", "You cannot go back from this question."],
};
class AssessmentApiError extends Error {
  constructor(readonly code: string) { super(code); }
}
type QuestionTranslation = {
  prompt: string;
  options: Array<{ id: string; text: string }>;
  explanation: string | null;
};
const codeLine = /^(?:\d+:\s|package\b|import\b|@\w+|(?:public|private|protected|static|final|abstract|class|interface|enum|record)\b|[{}]|\(.*\)\s*->)|[;{}]|::/;
function prose(value: string) {
  return value.split(/\n{2,}/).map((paragraph) => paragraph.replace(/\s*\n\s*/g, " ").trim()).filter(Boolean).join("\n\n");
}
function CodeViewer({ code, language, compact = false }: { code: string; language: Language; compact?: boolean }) {
  const [copied, setCopied] = useState(false);
  const tokens = highlightJava(code);

  async function copyCode() {
    if (!navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  return <figure className={`qa-code-viewer${compact ? " qa-code-viewer-compact" : ""}`}>
    <figcaption className="qa-code-toolbar">
      <span><i aria-hidden="true" />Java</span>
      {!compact ? <button type="button" onClick={copyCode} aria-label={translate(language, "Kodu kopyala", "Copy code")}>{copied ? translate(language, "Kopyalandı", "Copied") : translate(language, "Kopyala", "Copy")}</button> : null}
    </figcaption>
    <pre className={compact ? "qa-code-block qa-option-code" : "qa-code-block"}><code>{tokens.map((token, index) => token.kind === "plain" ? token.text : <span className={`qa-token qa-token-${token.kind}`} key={`${index}-${token.kind}`}>{token.text}</span>)}</code></pre>
  </figure>;
}
function QuestionText({ text, language, option = false }: { text: string; language: Language; option?: boolean }) {
  const lines = text.split("\n");
  const codeStart = lines.findIndex((line) => codeLine.test(line.trim()));
  if (codeStart < 0) {
    const inlineCode = option && /(?:\w+\(.*\)|::|->|\[\]|==|!=)/.test(text);
    return inlineCode ? <code className="qa-inline-code">{text}</code> : <span>{prose(text)}</span>;
  }
  const introduction = prose(lines.slice(0, codeStart).join("\n"));
  const code = lines.slice(codeStart).join("\n").trim();
  return <>
    {introduction ? <span className="qa-question-copy">{introduction}</span> : null}
    <CodeViewer code={code} language={language} compact={option} />
  </>;
}
function translationKey(question: PublicQuestion) {
  return `${question.id}:${question.version}`;
}
function readTranslation(question: PublicQuestion): QuestionTranslation | null {
  try {
    const raw = localStorage.getItem(`ai-interviewer:translation:az:${translationKey(question)}`);
    if (!raw) return null;
    const value = JSON.parse(raw) as QuestionTranslation;
    return typeof value.prompt === "string" && Array.isArray(value.options)
      && value.options.length === question.options.length ? value : null;
  } catch { return null; }
}
function localizedQuestion(question: PublicQuestion, translation?: QuestionTranslation): PublicQuestion {
  if (!translation) return question;
  const options = question.options.map((option) => translation.options.find((item) => item.id === option.id) ?? option);
  return { ...question, prompt: translation.prompt, options };
}
async function api(path: string, input?: object): Promise<AssessmentView | null> {
  const response = await fetch(path, { method: input ? "POST" : "GET", cache: "no-store",
    ...(input ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) } : {}) });
  const body = await response.json();
  if (!response.ok) throw new AssessmentApiError(body.code ?? "request_failed");
  return body.assessment;
}
function draftSelection(assessment: AssessmentView | null): string[] {
  if (!assessment?.question) return [];
  try {
    const draft = localStorage.getItem(`intervia:draft:${assessment.id}:${assessment.question.id}`);
    const value: unknown = draft ? JSON.parse(draft) : null;
    return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : assessment.selected;
  } catch { return assessment.selected; }
}
function References({ items, language }: { items: Reference[]; language: Language }) {
  return <ul className="qa-references">{items.map((item) => <li key={item.url}><a href={item.url} target="_blank" rel="noreferrer">{item.title} <span aria-hidden="true">↗</span></a></li>)}{!items.length ? <li>{translate(language, "Mənbə yoxdur", "No references")}</li> : null}</ul>;
}
function Feedback({ feedback, translation, busy, language, onRate }: { feedback: AnswerFeedback; translation?: QuestionTranslation; busy: boolean; language: Language; onRate: (input: object) => void }) {
  const q = localizedQuestion(feedback.question, language === "az" ? translation : undefined);
  const t = (az: string, en: string) => translate(language, az, en);
  const chosen = q.options.filter((option) => feedback.selected.includes(option.id)).map((option) => option.text).join("; ");
  const correct = q.options.filter((option) => feedback.correct.includes(option.id)).map((option) => option.text).join("; ");
  return <section className="qa-feedback" aria-labelledby={`feedback-${q.id}`}>
    <div className="qa-feedback-heading"><div><p className="eyebrow">{t("Cavabın təhlili", "Answer feedback")}</p><h2 id={`feedback-${q.id}`}>{feedback.skipped ? t("Buraxılıb", "Skipped") : feedback.score === 10 ? t("Düzgün cavab", "Correct answer") : t("Nəzərdən keçirin", "Review this answer")}</h2></div><strong className="qa-answer-score">{feedback.skipped ? "—" : feedback.score}<span>{feedback.skipped ? "" : " / 10"}</span></strong></div>
    <div className="qa-feedback-explanation"><QuestionText text={language === "az" && translation?.explanation ? translation.explanation : feedback.explanation} language={language} /></div>
    <div className="qa-answer-review"><p><b>{t("Sizin cavabınız:", "Your answer:")}</b> {feedback.skipped ? t("Buraxılıb", "Skipped") : chosen}</p><p><b>{t("Düzgün cavab:", "Correct answer:")}</b> {correct}</p></div>
    <h3>{t("Mənbə", "Source")}</h3><References items={feedback.references} language={language} />
    <div className="qa-question-feedback"><fieldset disabled={busy}><legend>{t("Bu sual faydalı idi?", "Was this question useful?")}</legend><div className="qa-stars">{[1, 2, 3, 4, 5].map((rating) => <button key={rating} type="button" aria-label={t(`${rating}/5 ulduz`, `Rate ${rating} out of 5 stars`)} aria-pressed={feedback.rating === rating} onClick={() => onRate({ questionId: q.id, rating })} className={(feedback.rating ?? 0) >= rating ? "selected" : ""}>★</button>)}</div>{feedback.rating ? <small role="status">{t("Saxlanıldı", "Saved")}: {feedback.rating}/5</small> : null}</fieldset>
      <label>{t("Problem bildir", "Report an issue")}<select disabled={busy} value={feedback.flag ?? ""} onChange={(event) => onRate({ questionId: q.id, flag: event.target.value || null })}><option value="">{t("Problem yoxdur", "No issue reported")}</option><option value="incorrect">{t("Cavab səhv görünür", "Answer seems incorrect")}</option><option value="unclear">{t("Sual aydın deyil", "Question is unclear")}</option><option value="too_difficult">{t("Çox çətindir", "Too difficult")}</option><option value="source">{t("Mənbəni yoxlayın", "Source needs review")}</option></select>{feedback.flag ? <small role="status">{t("Yoxlama üçün saxlanıldı", "Saved for review")}</small> : null}</label>
    </div>
  </section>;
}

export default function AssessmentPage() {
  const [language, setLanguage] = useState<Language>("az");
  const [mode, setMode] = useState<"roadmap" | "book">("roadmap");
  const [level, setLevel] = useState<Level>("Junior");
  const [topicIds, setTopicIds] = useState<string[]>(defaultTopics.Junior);
  const [companyMode, setCompanyMode] = useState(false);
  const [company, setCompany] = useState("");
  const [roadmapDepth, setRoadmapDepth] = useState<1 | 2 | 3>(3);
  const [bookQuestionCount, setBookQuestionCount] = useState(15);
  const [assessment, setAssessment] = useState<AssessmentView | null>(null);
  const [screen, setScreen] = useState<"setup" | "assessment">("setup");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [finishPrompt, setFinishPrompt] = useState(false);
  const [questionTranslations, setQuestionTranslations] = useState<Record<string, QuestionTranslation>>({});
  const [translationErrors, setTranslationErrors] = useState<string[]>([]);
  const pendingTranslations = useRef(new Set<string>());
  const requestId = useRef<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const t = (az: string, en: string) => translate(language, az, en);
  const question = assessment?.question;
  const finished = screen === "assessment" && assessment?.status === "completed";
  const draftKey = assessment && question ? `intervia:draft:${assessment.id}:${question.id}` : null;
  const questionCount = mode === "book" ? bookQuestionCount : topicIds.length * roadmapDepth;

  const fetchTranslation = useCallback(async (target: PublicQuestion, review = false) => {
    await Promise.resolve();
    if (language !== "az" || !assessment?.id) return;
    const key = translationKey(target);
    const cached = readTranslation(target);
    if (cached && (!review || cached.explanation)) {
      setQuestionTranslations((current) => current[key] === cached ? current : { ...current, [key]: cached });
      return;
    }
    const requestKey = `${key}:${review ? "review" : "question"}`;
    if (pendingTranslations.current.has(requestKey)) return;
    pendingTranslations.current.add(requestKey);
    try {
      const response = await fetch(`/api/assessments/${assessment.id}/translations/${target.id}${review ? "?review=1" : ""}`, { cache: "no-store" });
      const body = await response.json();
      if (!response.ok || !body.translation) throw new Error(body.code ?? "translation_unavailable");
      const next = { ...(cached ?? {}), ...body.translation } as QuestionTranslation;
      localStorage.setItem(`ai-interviewer:translation:az:${key}`, JSON.stringify(next));
      setQuestionTranslations((current) => ({ ...current, [key]: next }));
      setTranslationErrors((current) => current.filter((item) => item !== key));
    } catch {
      setTranslationErrors((current) => current.includes(key) ? current : [...current, key]);
    } finally {
      pendingTranslations.current.delete(requestKey);
    }
  }, [assessment, language]);

  useEffect(() => {
    let active = true;
    api("/api/assessments").then((saved) => {
      if (!active) return;
      const savedLanguage = localStorage.getItem("intervia:language");
      if (savedLanguage === "az" || savedLanguage === "en") setLanguage(savedLanguage);
      setAssessment(saved);
      setSelected(draftSelection(saved));
      if (saved?.status === "active") setScreen("assessment");
    }).catch((cause: Error) => { if (active) setError(cause); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => { document.documentElement.lang = language; }, [language]);
  useEffect(() => { if (screen === "assessment") heading.current?.focus(); }, [screen, question?.id, finished]);
  useEffect(() => {
    if (!question) return;
    const timer = window.setTimeout(() => { void fetchTranslation(question); }, 0);
    return () => window.clearTimeout(timer);
  }, [fetchTranslation, question]);

  function choose(next: string[]) {
    setSelected(next);
    if (draftKey) localStorage.setItem(draftKey, JSON.stringify(next));
  }
  function changeLevel(next: Level) { setLevel(next); setTopicIds(defaultTopics[next]); requestId.current = null; }
  async function start(event: FormEvent) {
    event.preventDefault();
    if (busy || (mode === "roadmap" && !topicIds.length)) return;
    setBusy(true); setError(null);
    requestId.current ??= crypto.randomUUID();
    try {
      const saved = await api("/api/assessments", mode === "book"
        ? { requestId: requestId.current, mode: "book", questionCount }
        : { requestId: requestId.current, mode: "roadmap", level, topicIds, questionCount, company: companyMode ? company : null });
      setAssessment(saved); setSelected([]); setFinishPrompt(false); setScreen("assessment"); requestId.current = null;
    } catch (cause) { setError(cause as Error); }
    finally { setBusy(false); }
  }
  async function mutate(input: object, submitted = false) {
    if (!assessment || busy) return;
    setBusy(true); setError(null);
    try {
      const saved = await api(`/api/assessments/${assessment.id}`, input);
      if (submitted && draftKey) localStorage.removeItem(draftKey);
      if (submitted && assessment.mode === "roadmap" && assessment.currentIndex < assessment.completedCount) {
        for (const key of Object.keys(localStorage)) if (key.startsWith(`intervia:draft:${assessment.id}:`)) localStorage.removeItem(key);
      }
      setAssessment(saved); setSelected(draftSelection(saved)); setFinishPrompt(false);
    } catch (cause) { setError(cause as Error); }
    finally { setBusy(false); }
  }
  async function finishCurrent() {
    if (!assessment || !question || busy) return;
    setBusy(true); setError(null);
    try {
      const saved = await api(`/api/assessments/${assessment.id}`, { action: "answer", questionId: question.id, selected: selected.length ? selected : null });
      if (draftKey) localStorage.removeItem(draftKey);
      if (!saved?.readyToFinish) { setAssessment(saved); setSelected(draftSelection(saved)); return; }
      setAssessment(await api(`/api/assessments/${assessment.id}`, { action: "finish" }));
      setSelected([]); setFinishPrompt(false);
    } catch (cause) { setError(cause as Error); }
    finally { setBusy(false); }
  }
  async function reload() {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const saved = await api(assessment ? `/api/assessments/${assessment.id}` : "/api/assessments");
      setAssessment(saved); setSelected(draftSelection(saved)); setFinishPrompt(false);
      setScreen(saved?.status === "active" ? "assessment" : "setup");
    } catch (cause) { setError(cause as Error); }
    finally { setBusy(false); }
  }
  function newAssessment() { setScreen("setup"); setError(null); setFinishPrompt(false); requestId.current = null; }
  const errorCode = error instanceof AssessmentApiError ? error.code : "request_failed";
  const errorText = errorMessages[errorCode];
  const activeTranslation = question ? questionTranslations[translationKey(question)] : undefined;
  const displayQuestion = question ? localizedQuestion(question, language === "az" ? activeTranslation : undefined) : null;
  const activeTranslationFailed = question ? translationErrors.includes(translationKey(question)) : false;

  return <div className="qa-app">
    <a className="qa-skip-link" href="#qa-main">{t("Əsas məzmuna keç", "Skip to content")}</a>
    <header className="qa-header"><div><Brand /><span className="qa-header-label">{t("Java istiqaməti", "Java track")}</span><div className="qa-header-actions"><a href={roadmapUrl} target="_blank" rel="noreferrer">{t("Yol xəritəsi ↗", "Explore the roadmap ↗")}</a><label className="qa-language">{t("Dil", "Language")}<select value={language} onChange={(event) => { const next = event.target.value as Language; localStorage.setItem("intervia:language", next); setLanguage(next); }}><option value="az">AZ</option><option value="en">EN</option></select></label><PortalAccountChip language={language} /></div></div></header>
    <main id="qa-main" className="qa-main" tabIndex={-1}>
      <nav className="qa-breadcrumb" aria-label={t("Səhifə yolu", "Breadcrumb")}><Link href="/">← {t("Bütün istiqamətlər", "All tracks")}</Link><span aria-hidden="true">/</span><span>Java</span></nav>
      {error ? <div className="qa-error" role="alert"><p>{errorText ? translate(language, ...errorText) : t("Dəyişiklik saxlanmadı. Yenidən cəhd edin.", "Your change could not be saved. Please try again.")}</p><button type="button" disabled={busy} onClick={reload}>{t("Saxlanmış testi yenilə", "Reload saved assessment")}</button></div> : null}
      {loading ? <p className="qa-loading" role="status">{t("Saxlanmış test yoxlanılır…", "Checking for a saved assessment…")}</p> : screen === "setup" ? <>
        <section className="qa-hero">
          <div>
            <p className="eyebrow">{t("Biliklərinizi sınayın", "Check your knowledge")}</p>
            <h1>{t("Java biliklərinizi", "Build confidence in")}<br /><em>{t("AI Interviewer ilə yoxlayın.", "your Java knowledge.")}</em></h1>
            <p className="qa-lead">{t("Sualları öz tempinizdə cavablandırın, istədiyinizi buraxın və nəticələri yalnız sonda görün.", "Answer at your own pace, skip questions, and see all results at the end.")}</p>
            <a className="button button-primary qa-hero-cta" href="#qa-start">{t("Testinizi seçin", "Choose your assessment")} <span aria-hidden="true">→</span></a>
            <div className="qa-hero-pills"><span>{t("Geri qayıda bilərsiniz", "Go back anytime")}</span><span>{t("Cavablar sonda", "Answers at the end")}</span><span>{t("Sessiyanız saxlanır", "Your session is saved")}</span></div>
          </div>
          <aside className="qa-preview" aria-label={t("Test haqqında", "About the assessment")}>
            <div className="qa-preview-top"><span>AI INTERVIEWER</span><span>JAVA</span></div>
            <p>{t("Öyrənin. Sınayın. Davam edin.", "Learn. Test. Continue.")}</p>
            <div className="qa-preview-option"><span aria-hidden="true">✓</span>{t("Cavablarını test bitəndə birlikdə nəzərdən keçir.", "Review all your answers once the assessment ends.")}</div>
            <p className="qa-preview-note">{t("Java və AI mövzuları və ya Java 8 kitabı üzrə məşq seç.", "Choose Java & AI topics or practice with the Java 8 book.")}</p>
          </aside>
        </section>
        <div id="qa-start" className="qa-start-anchor" aria-hidden="true" />
        {assessment ? <section className="qa-resume"><div><b>{assessment.status === "active" ? t("Testiniz saxlanılıb", "Your assessment is saved") : t("Son nəticəniz", "Your latest result")}</b><span>{assessment.mode === "book" ? t("Java 8 kitabı", "Java 8 book practice") : levelNames[assessment.level]} · {assessment.answered} {t("cavab", "answered")}{assessment.skipped ? ` · ${assessment.skipped} ${t("buraxılıb", "skipped")}` : ""}</span></div><button type="button" className="button button-secondary" onClick={() => { setScreen("assessment"); setError(null); }}>{assessment.status === "active" ? t("Davam et →", "Continue →") : t("Nəticəyə bax →", "View result →")}</button></section> : null}
        <form onSubmit={start} className="qa-setup"><div className="qa-section-heading"><div><p className="eyebrow">{t("Başlanğıc", "Your starting point")}</p><h2>{t("Testinizi seçin.", "Make this assessment yours.")}</h2></div><p>{t(`${questionCount} suala qədər · Öz tempinizdə`, `Up to ${questionCount} questions · At your pace`)}</p></div>
          <fieldset className="qa-mode"><legend>{t("Sual mənbəyi", "Choose a question set")}</legend><div><label><input type="radio" name="mode" checked={mode === "roadmap"} disabled={busy} onChange={() => { setMode("roadmap"); requestId.current = null; }} /><span><b>{t("Java və AI testi", "Java & AI assessment")}</b><small>{t("Mövzu və səviyyəyə uyğunlaşan, Azərbaycan və ingilis dillərində suallar.", "Adaptive questions from the general bank in Azerbaijani and English.")}</small></span></label><label><input type="radio" name="mode" checked={mode === "book"} disabled={busy} onChange={() => { setMode("book"); requestId.current = null; }} /><span><b>{t("Java 8 kitabı üzrə məşq", "Java 8 book practice")}</b><small>{t("1075 yayımlanmış kitab sualından istədiyiniz uzunluqda təsadüfi seçim.", "Choose the test length and sample from 1,075 published book questions.")}</small></span></label></div></fieldset>
          {mode === "roadmap" ? <><fieldset className="qa-levels" disabled={busy}><legend>{t("1. Səviyyəni seç", "1. Choose your level")}</legend><div>{levels.map((item, index) => <label key={item} className={level === item ? "active" : ""}><input type="radio" name="level" checked={level === item} onChange={() => changeLevel(item)} /><span className="qa-level-number">0{index + 1}</span><b>{language === "az" ? levelNames[item] : item}</b><small>{item === "Junior" ? t("Java və backend əsasları", "Everyday Java & backend foundations") : item === "Mid" ? t("İstehsal sistemləri və AI", "Production services & AI integration") : t("Paralellik, paylanmış sistemlər və AI", "Concurrency, distributed systems & AI reliability")}</small><span className="qa-radio-dot" aria-hidden="true" /></label>)}</div></fieldset>
            <fieldset className="qa-topics" disabled={busy}><legend>{t("2. Altı mövzuya qədər seç", "2. Pick up to six topics")} <span>{topicIds.length} {t("seçilib", "selected")}</span></legend><div>{availableTopics(level).map((topic) => <label key={topic.id} className={topicIds.includes(topic.id) ? "active" : ""}><input type="checkbox" checked={topicIds.includes(topic.id)} disabled={!topicIds.includes(topic.id) && topicIds.length >= 6} onChange={(event) => { setTopicIds(event.target.checked ? [...topicIds, topic.id] : topicIds.filter((id) => id !== topic.id)); requestId.current = null; }} /><span><b>{language === "az" ? topicNames[topic.id] : topic.title}</b><small>{language === "en" ? topic.summary : t("Mövzu üzrə suallar", "Questions in this topic")}</small></span></label>)}</div></fieldset>
            <div className="qa-company"><label className="qa-toggle"><input type="checkbox" checked={companyMode} disabled={busy} onChange={(event) => { setCompanyMode(event.target.checked); requestId.current = null; }} /><span><b>{t("Şirkət konteksti əlavə et", "Add company context")}</b><small>{t("İstəyə bağlıdır. Ümumi test əsas seçimdir.", "Optional. Your assessment is general by default.")}</small></span></label>{companyMode ? <div className="qa-company-input"><label>{t("Şirkətin adı", "Company name")}<input disabled={busy} required value={company} maxLength={100} placeholder="məs. PASHA Bank" onChange={(event) => { setCompany(event.target.value); requestId.current = null; }} /></label><p>{t("Yalnız mənbəsi məlum olan şirkət sualları istifadə olunur. Mövcud deyilsə, ümumi suallar göstərilir.", "Only sourced company questions are used. Otherwise you receive general questions.")}</p></div> : null}</div></> : null}
          <fieldset className="qa-length" disabled={busy}>
            <legend>{mode === "roadmap" ? t("3. Test dərinliyini seç", "3. Choose assessment depth") : t("Sual sayını seç", "Choose the number of questions")}</legend>
            <div>{mode === "roadmap" ? ([1, 2, 3] as const).map((depth) => <label key={depth} className={roadmapDepth === depth ? "active" : ""}>
              <input type="radio" name="roadmap-depth" checked={roadmapDepth === depth} onChange={() => { setRoadmapDepth(depth); requestId.current = null; }} />
              <b>{depth === 1 ? t("Qısa", "Quick") : depth === 2 ? t("Balanslı", "Balanced") : t("Dərin", "Deep")}</b>
              <strong>{topicIds.length * depth} {t("suala qədər", "questions maximum")}</strong><small>{t(`Hər mövzudan ${depth} suala qədər`, `Up to ${depth} per topic`)}</small>
            </label>) : [10, 15, 25, 50].map((count) => <label key={count} className={bookQuestionCount === count ? "active" : ""}>
              <input type="radio" name="book-count" checked={bookQuestionCount === count} onChange={() => { setBookQuestionCount(count); requestId.current = null; }} />
              <b>{count}</b><small>{t("kitab sualı", "book questions")}</small>
            </label>)}</div>
          </fieldset>
          <div className="qa-start"><div><b>{mode === "book" ? t("Kitabla məşq et.", "Practice with the book.") : t("Asandan başla.", "Start simple.")}</b><p>{mode === "book" ? t(`${questionCount} sual seçilir. Vizual yoxlama tələb edənlər daxil edilmir.`, `${questionCount} questions are sampled. Items needing visual review are excluded.`) : t(`Seçiminizə görə ${questionCount} suala qədər göstəriləcək. Düzgün cavablar daha çətin suallara keçir.`, `Your selection allows up to ${questionCount} questions. Strong answers unlock harder questions.`)}</p></div><button type="submit" className="button button-primary" disabled={busy || (mode === "roadmap" && (!topicIds.length || (companyMode && !company.trim())))}>{busy ? t("Hazırlanır…", "Preparing…") : t("Testə başla", "Start assessment")} →</button></div>
        </form>{mode === "roadmap" ? <p className="qa-roadmap-note">{t("Mövzular", "Scope guided by the")} <a href={roadmapUrl} target="_blank" rel="noreferrer">Ingress Academy Java & AI Engineer roadmap</a> {t("yol xəritəsinə əsaslanır.", "roadmap.")}</p> : null}
      </> : assessment ? <><div className="qa-session-heading"><div><p className="eyebrow">{finished ? t("Nəticə", "Your result") : assessment.mode === "book" ? t("Java 8 kitabı üzrə məşq", "Java 8 book practice") : `${language === "az" ? levelNames[assessment.level] : assessment.level} · Java`}</p><h1 ref={heading} tabIndex={-1}>{finished ? t("Nəticələriniz hazırdır.", "Your results are ready.") : assessment.mode === "book" ? question?.tags[2] : language === "az" ? topicNames[question?.topic ?? ""] : topics.find((topic) => topic.id === question?.topic)?.title}</h1></div><button type="button" className="qa-text-button" disabled={busy} onClick={newAssessment}>{t("Yeni test", "New assessment")}</button></div>
        {assessment.companyNotice ? <p className="qa-notice">{assessment.companyNotice}</p> : null}
        {!finished ? <><div className="qa-progress-label"><span>{t("Sual", "Question")} {assessment.currentIndex} · {assessment.answered} {t("cavablandı", "answered")} · {assessment.skipped} {t("buraxıldı", "skipped")}</span><b>{t("Maksimum", "Up to")} {assessment.maximumQuestions} {t("sual", "questions")}</b></div><progress className="qa-progress" value={assessment.completedTopics} max={assessment.totalTopics} aria-label={t(`${assessment.completedCount} sual tamamlanıb`, `${assessment.completedCount} questions completed`)} />
          {question && displayQuestion ? <section className="qa-question" key={question.id}><div className="qa-question-meta"><span>{question.type === "single" ? t("Bir cavab seç", "Choose one answer") : t("Bütün düzgün cavabları seç", "Select all correct answers")}</span><span>{language === "az" && !activeTranslation ? activeTranslationFailed ? "Orijinal mətn göstərilir" : "Azərbaycancaya çevrilir…" : assessment.mode === "book" ? question.tags[1] : `${t("Çətinlik", "Complexity")} ${question.complexity}/10`}</span></div><form onSubmit={(event) => { event.preventDefault(); mutate({ action: "answer", questionId: question.id, selected }, true); }}><fieldset disabled={busy}><legend className="qa-visually-hidden">{t("Sual", "Question")}</legend><div className="qa-question-prompt"><QuestionText text={displayQuestion.prompt} language={language} /></div><div className="qa-options">{displayQuestion.options.map((option, index) => <label key={option.id} className={selected.includes(option.id) ? "selected" : ""}><input type={question.type === "single" ? "radio" : "checkbox"} name="answer" value={option.id} checked={selected.includes(option.id)} onChange={(event) => choose(question.type === "single" ? [option.id] : event.target.checked ? [...selected, option.id] : selected.filter((id) => id !== option.id))} /><span className="qa-option-letter" aria-hidden="true">{String.fromCharCode(65 + index)}</span><span className="qa-option-text"><QuestionText text={option.text} language={language} option /></span></label>)}</div></fieldset><div className="qa-question-source"><div className="qa-tags">{question.tags.map((tag) => <span key={tag}>{tag}</span>)}</div><p>{t("Mənbə", "Source")}: <a href={question.source.url} target="_blank" rel="noreferrer">{question.source.title} ↗</a></p></div><div className="qa-question-submit"><p>{language === "az" && activeTranslationFailed ? "Azərbaycan dilində tərcümə hazırda əlçatan deyil; orijinal mətn göstərilir." : t("Kod nümunələri dəyişdirilmədən saxlanılır. Düzgün cavablar testin sonunda göstəriləcək.", "Code samples are preserved exactly. Correct answers appear at the end.")}</p><div className="qa-question-actions"><button type="button" className="button button-secondary" disabled={busy} onClick={() => assessment.canGoBack ? mutate({ action: "back" }) : newAssessment()} aria-label={assessment.canGoBack ? t("Əvvəlki suala qayıt", "Go to previous question") : t("Test seçiminə qayıt", "Back to assessment setup")}>{t("← Geri", "← Back")}</button><button type="button" className="button button-secondary" disabled={busy} onClick={() => mutate({ action: "answer", questionId: question.id, selected: null }, true)}>{t("Boş burax", "Skip")}</button><button type="submit" className="button button-primary" disabled={busy || !selected.length}>{busy ? t("Saxlanır…", "Saving…") : assessment.readyToFinish ? t("Cavabı saxla", "Save answer") : t("Növbəti →", "Next →")}</button></div></div></form></section> : null}
          {assessment.mode === "roadmap" && assessment.canGoBack ? <p className="qa-navigation-note">{t("Əvvəlki cavabı dəyişsəniz, ondan sonrakı adaptiv suallar yenidən seçiləcək.", "Changing an earlier answer recalculates the later adaptive questions.")}</p> : null}
          {assessment.readyToFinish ? <div className="qa-finish-early"><button type="button" className="button button-primary" disabled={busy} onClick={finishCurrent}>{t("Bitir və nəticəyə bax →", "Finish and see results →")}</button></div> : assessment.completedCount > 0 ? <div className="qa-finish-early">{finishPrompt ? <><p>{t("İndi bitirmək istəyirsiniz? Bal yalnız cavablandırdığınız suallara görə hesablanacaq.", "Finish now? Only answered questions count toward your score.")}</p><button disabled={busy} type="button" className="button button-secondary" onClick={() => mutate({ action: "finish" })}>{t("Bitir və nəticəyə bax", "Finish and see results")}</button><button type="button" disabled={busy} className="qa-text-button" onClick={() => setFinishPrompt(false)}>{t("Davam et", "Keep going")}</button></> : <button className="qa-text-button" type="button" disabled={busy} onClick={() => setFinishPrompt(true)}>{t("Testi erkən bitir", "Finish assessment early")}</button>}</div> : null}
        </> : <><section className="qa-result-hero">
          <div>
            <p className="eyebrow">{t("Ümumi nəticə", "Overall score")}</p>
            <strong className="qa-total-score">{assessment.percent ?? "—"}<span>{assessment.percent === null ? "" : "%"}</span></strong>
            <p className="qa-score-caption">{t("Cavablandırılan suallar üzrə", "Of answered questions")}</p>
            <p className="qa-total-points">{assessment.earned} / {assessment.possible} {t("bal", "points")} · {assessment.completedCount} {t("sual tamamlandı", "questions completed")} · {t("maksimum", "up to")} {assessment.maximumQuestions}</p>
          </div>
          <div>
            <span className="qa-result-level">{assessment.mode === "book" ? t("Java 8 kitabı", "Java 8 book") : language === "az" ? levelNames[assessment.level] : assessment.level}</span>
            <h2>{t("Cavablarınızı nəzərdən keçirin.", "Review your answers.")}</h2>
            <p>{assessment.mode === "book" ? t(`${assessment.answered} cavab, ${assessment.skipped} buraxılmış sual.`, `${assessment.answered} answers and ${assessment.skipped} skips.`) : t("Bu nəticə yalnız cavablandırdığınız mövzulara əsaslanır.", assessment.summary)}</p>
            {assessment.finishedEarly ? <p>{t("Test erkən bitirilib. Buraxılan suallar bala daxil deyil.", "Finished early. Skipped questions do not count toward your score.")}</p> : null}
          </div>
        </section>
          {assessment.mode === "roadmap" ? <section className="qa-results">
            <h2>{t("Mövzular üzrə nəticə", "Results by topic")}</h2>
            <div className="qa-table-wrap"><table>
              <thead><tr><th>{t("Mövzu", "Topic")}</th><th>{t("Bal", "Points")}</th><th>{t("Çətinlik", "Difficulty reached")}</th><th>{t("Vəziyyət", "Status")}</th></tr></thead>
              <tbody>{assessment.results.map((result) => <tr key={result.id}>
                <th scope="row">{language === "az" ? topicNames[result.id] : result.title}<small>{result.answered} {t("cavab", "answered")}</small></th>
                <td data-label={t("Bal", "Points")}>{result.possible ? `${result.earned} / ${result.possible}` : "—"}</td>
                <td data-label={t("Çətinlik", "Difficulty")}>{result.highestPassed === null ? "—" : `${result.highestPassed}/10`}</td>
                <td data-label={t("Vəziyyət", "Status")}>{result.status === "strong" ? t("Güclü", "Strong") : result.status === "developing" ? t("İnkişaf edir", "Developing") : result.status === "revisit" ? t("Təkrar et", "Revisit") : t("Qiymətləndirilməyib", "Not assessed")}</td>
              </tr>)}</tbody>
            </table></div>
          </section> : null}
          <section className="qa-history"><h2>{t("Suallar və cavablar", "Questions and answers")}</h2>{assessment.history.map((answer, index) => {
            const answerTranslation = questionTranslations[translationKey(answer.question)];
            const translated = localizedQuestion(answer.question, language === "az" ? answerTranslation : undefined);
            return <details key={answer.question.id} onToggle={(event) => { if (event.currentTarget.open) void fetchTranslation(answer.question, true); }}><summary><span>{index + 1}. {prose(translated.prompt)}</span><b>{answer.skipped ? "—" : `${answer.score}/10`}</b></summary><Feedback feedback={answer} translation={answerTranslation} busy={busy} language={language} onRate={(input) => mutate({ action: "feedback", ...input })} /></details>;
          })}</section>
          <div className="qa-result-actions"><button type="button" className="button button-primary" onClick={newAssessment}>{t("Yeni testə başlayın →", "Start another assessment →")}</button><button type="button" className="button button-secondary" onClick={() => window.print()}>{t("Çap edin / saxlayın", "Print / save result")}</button></div>
        </>}
      </> : null}
    </main><footer className="qa-footer"><span>AI Interviewer · {t("Öyrənməyə davam et.", "Keep learning.")}</span><span>Java & AI</span></footer>
  </div>;
}
