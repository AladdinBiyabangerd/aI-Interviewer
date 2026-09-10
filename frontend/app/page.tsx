"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { availableTopics, defaultTopics, levels, roadmapUrl, topics, type AnswerFeedback, type AssessmentView, type Level, type Reference } from "../lib/assessment";
import "./assessment.css";

const errors: Record<string, string> = {
  topic_unavailable: "One of these topics has no published questions yet. Choose another topic or try again after the question bank is reviewed.",
  assessment_unavailable: "Assessments are temporarily unavailable. Please try again.",
  rate_limited: "You have started several assessments recently. Please wait a few minutes before starting another.",
  session_not_found: "This assessment has expired or belongs to another browser. Start a new assessment.",
  stale_question: "This question has already advanced in another tab. Reload the saved assessment to continue.",
  answer_already_saved: "An answer for this question is already saved. Reload the assessment to see it.",
};
async function api(path: string, input?: object): Promise<AssessmentView | null> {
  const response = await fetch(path, { method: input ? "POST" : "GET", cache: "no-store",
    ...(input ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) } : {}) });
  const result = await response.json();
  if (!response.ok) throw new Error(errors[result.code] ?? "Your change could not be saved. Please try again.");
  return result.assessment;
}
function References({ items }: { items: Reference[] }) {
  return <ul className="qa-references">{items.map((r) => <li key={r.url}><a href={r.url} target="_blank" rel="noreferrer">{r.title} <span aria-hidden="true">↗</span></a></li>)}</ul>;
}
function Feedback({ feedback, busy, onRate }: { feedback: AnswerFeedback; busy: boolean; onRate: (input: object) => void }) {
  const q = feedback.question;
  return <section className="qa-feedback" aria-labelledby={`feedback-${q.id}`}>
    <div className="qa-feedback-heading"><div><p className="eyebrow">Answer feedback</p><h2 id={`feedback-${q.id}`}>{feedback.score === 10 ? "You’ve got it." : feedback.score >= 7 ? "A good understanding." : feedback.score > 0 ? "Part of the picture." : "A useful place to learn."}</h2></div><strong className="qa-answer-score">{feedback.score}<span> / 10</span></strong></div>
    <p>{feedback.explanation}</p>
    <div className="qa-answer-review"><p><b>Your answer:</b> {q.options.filter((o) => feedback.selected.includes(o.id)).map((o) => o.text).join("; ")}</p><p><b>Correct answer{feedback.correct.length > 1 ? "s" : ""}:</b> {q.options.filter((o) => feedback.correct.includes(o.id)).map((o) => o.text).join("; ")}</p></div>
    <h3>Understand the idea</h3><References items={feedback.references} />
    <div className="qa-question-feedback"><fieldset disabled={busy}><legend>Was this question useful?</legend><div className="qa-stars">{[1, 2, 3, 4, 5].map((rating) => <button key={rating} type="button" aria-label={`Rate ${rating} out of 5 stars`} aria-pressed={feedback.rating === rating} onClick={() => onRate({ questionId: q.id, rating })} className={(feedback.rating ?? 0) >= rating ? "selected" : ""}>★</button>)}</div>{feedback.rating ? <small role="status">Saved: {feedback.rating}/5 stars</small> : null}</fieldset>
      <label>Report an issue<select disabled={busy} value={feedback.flag ?? ""} onChange={(e) => onRate({ questionId: q.id, flag: e.target.value || null })}><option value="">No issue reported</option><option value="incorrect">Answer seems incorrect</option><option value="unclear">Question is unclear</option><option value="too_difficult">Too difficult for this level</option><option value="source">Source needs review</option></select>{feedback.flag ? <small role="status">Saved for editorial review.</small> : null}</label>
    </div>
  </section>;
}

export default function AssessmentPage() {
  const [level, setLevel] = useState<Level>("Junior");
  const [topicIds, setTopicIds] = useState<string[]>(defaultTopics.Junior);
  const [companyMode, setCompanyMode] = useState(false);
  const [company, setCompany] = useState("");
  const [assessment, setAssessment] = useState<AssessmentView | null>(null);
  const [screen, setScreen] = useState<"setup" | "assessment">("setup");
  const [acknowledged, setAcknowledged] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [finishPrompt, setFinishPrompt] = useState(false);
  const requestId = useRef<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const feedback = assessment?.feedback;
  const showingFeedback = screen === "assessment" && feedback && acknowledged !== feedback.question.id;
  const question = assessment?.question;
  const finished = screen === "assessment" && assessment?.status === "completed" && !showingFeedback;

  useEffect(() => {
    let active = true;
    api("/api/assessments").then((saved) => { if (active) setAssessment(saved); })
      .catch((e: Error) => { if (active) setError(e.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => { if (screen === "assessment") heading.current?.focus(); }, [screen, question?.id, showingFeedback, finished]);

  function changeLevel(next: Level) { setLevel(next); setTopicIds(defaultTopics[next]); requestId.current = null; }
  async function start(event: FormEvent) {
    event.preventDefault();
    if (busy || !topicIds.length) return;
    setBusy(true); setError(null);
    requestId.current ??= crypto.randomUUID();
    try {
      const saved = await api("/api/assessments", { requestId: requestId.current, level, topicIds, company: companyMode ? company : null });
      setAssessment(saved); setAcknowledged(null); setSelected([]); setFinishPrompt(false); setScreen("assessment"); requestId.current = null;
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function mutate(input: object) {
    if (!assessment || busy) return;
    setBusy(true); setError(null);
    try {
      const saved = await api(`/api/assessments/${assessment.id}`, input);
      setAssessment(saved); setSelected([]); setFinishPrompt(false);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function reload() {
    setBusy(true); setError(null);
    try { setAssessment(await api(assessment ? `/api/assessments/${assessment.id}` : "/api/assessments")); setSelected([]); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function newAssessment() { setScreen("setup"); setError(null); setFinishPrompt(false); requestId.current = null; }

  return <div className="qa-app">
    <header className="qa-header"><div><button className="brand" type="button" onClick={newAssessment} disabled={busy}><span>IP</span><b>Interview Prep</b></button><span className="qa-header-label">Java knowledge assessment</span><a href={roadmapUrl} target="_blank" rel="noreferrer">Explore the roadmap ↗</a></div></header>
    <main className="qa-main">
      {error ? <div className="qa-error" role="alert"><p>{error}</p><button type="button" disabled={busy} onClick={reload}>Reload saved assessment</button></div> : null}
      {screen === "setup" ? <>
        <section className="qa-hero"><div><p className="eyebrow">Know where you stand. Know what’s next.</p><h1>Build confidence in<br /><em>your Java knowledge.</em></h1><p className="qa-lead">A focused check of the ideas behind the code. Start with the basics, find your strengths, and leave with a clear next step.</p><div className="qa-hero-pills"><span>Single & multiple choice</span><span>Instant scores</span><span>No CV needed</span></div></div>
          <aside className="qa-preview" aria-label="Example of answer feedback"><div className="qa-preview-top"><span>THE IDEA, NOT THE SYNTAX</span><span>Java</span></div><p>Why use dependency injection?</p><div className="qa-preview-option"><span aria-hidden="true">✓</span> Make dependencies explicit and easier to test.</div><div className="qa-preview-score"><div><small>EXAMPLE ANSWER SCORE</small><strong>10 <span>/ 10</span></strong></div><span className="qa-example">Illustrative example</span></div><p className="qa-preview-note">Understand the concept. Get feedback. Go one step deeper.</p></aside>
        </section>
        {loading ? <p role="status">Checking for a saved assessment…</p> : assessment ? <section className="qa-resume"><div><b>{assessment.status === "active" ? "Your assessment is saved" : "Your latest result"}</b><span>{assessment.level} · {assessment.answered} answered{assessment.percent !== null ? ` · ${assessment.percent}%` : ""}</span></div><button type="button" className="button button-secondary" onClick={() => { setScreen("assessment"); setAcknowledged(assessment.status === "completed" ? assessment.feedback?.question.id ?? null : null); setError(null); }}>{assessment.status === "active" ? "Continue assessment →" : "View result →"}</button></section> : null}
        <form onSubmit={start} className="qa-setup">
          <div className="qa-section-heading"><div><p className="eyebrow">Your starting point</p><h2>Make this assessment yours.</h2></div><p>Questions in English · About 10–15 minutes</p></div>
          <fieldset className="qa-levels" disabled={busy}><legend>1. Choose the level you want to check</legend><div>{levels.map((item, i) => <label key={item} className={level === item ? "active" : ""}><input type="radio" name="level" checked={level === item} onChange={() => changeLevel(item)} /><span className="qa-level-number">0{i + 1}</span><b>{item}</b><small>{item === "Junior" ? "Everyday Java & backend foundations" : item === "Mid" ? "Production services & AI integration" : "Concurrency, distributed systems & AI reliability"}</small><span className="qa-radio-dot" aria-hidden="true" /></label>)}</div></fieldset>
          <fieldset className="qa-topics" disabled={busy}><legend>2. Pick up to six topics <span>{topicIds.length} selected</span></legend><div>{availableTopics(level).map((topic) => <label key={topic.id} className={topicIds.includes(topic.id) ? "active" : ""}><input type="checkbox" checked={topicIds.includes(topic.id)} disabled={!topicIds.includes(topic.id) && topicIds.length >= 6} onChange={(e) => { setTopicIds(e.target.checked ? [...topicIds, topic.id] : topicIds.filter((id) => id !== topic.id)); requestId.current = null; }} /><span><b>{topic.title}</b><small>{topic.summary}</small></span></label>)}</div></fieldset>
          <div className="qa-company"><label className="qa-toggle"><input type="checkbox" checked={companyMode} disabled={busy} onChange={(e) => { setCompanyMode(e.target.checked); requestId.current = null; }} /><span><b>Add company context</b><small>Optional. Your assessment is general by default.</small></span></label>{companyMode ? <div className="qa-company-input"><label>Company name<input disabled={busy} required value={company} maxLength={100} placeholder="e.g. PASHA Bank or Revolut" onChange={(e) => { setCompany(e.target.value); requestId.current = null; }} /></label><p>Only sourced interview evidence is used. If none is available, you’ll receive general questions. Company questions never exceed 20% of the assessment.</p></div> : null}</div>
          <div className="qa-start"><div><b>Start simple. Build from there.</b><p>Up to {topicIds.length * 3} questions. Strong answers unlock harder ones.<br />If a question trips you up, we’ll move to the next topic.</p></div><button type="submit" className="button button-primary" disabled={busy || loading || !topicIds.length || (companyMode && !company.trim())}>{busy ? "Preparing…" : "Start assessment"} <span aria-hidden="true">→</span></button></div>
        </form>
        <p className="qa-roadmap-note">Scope guided by the <a href={roadmapUrl} target="_blank" rel="noreferrer">Ingress Academy Java & AI Engineer roadmap</a>. Questions focus on understanding, with references for further study.</p>
      </> : assessment ? <>
        <div className="qa-session-heading"><div><p className="eyebrow">{finished ? "Your knowledge snapshot" : `${assessment.level} · Java assessment`}</p><h1 ref={heading} tabIndex={-1}>{finished ? "A clearer picture of your progress." : showingFeedback ? "Learn from each answer." : topics.find((t) => t.id === question?.topic)?.title}</h1></div><button type="button" className="qa-text-button" disabled={busy} onClick={newAssessment}>New assessment</button></div>
        {assessment.companyNotice ? <p className="qa-notice">{assessment.companyNotice}</p> : null}
        {!finished ? <>
          <div className="qa-progress-label"><span>{assessment.answered} answered · Up to {assessment.maximumQuestions} questions</span><b>{assessment.earned} / {assessment.possible} points earned</b></div><progress className="qa-progress" value={assessment.completedTopics} max={assessment.totalTopics} aria-label={`${assessment.completedTopics} of ${assessment.totalTopics} topics completed`} />
          {showingFeedback && feedback ? <><Feedback feedback={feedback} busy={busy} onRate={(input) => mutate({ action: "feedback", ...input })} /><div className="qa-next"><p>{assessment.status === "completed" ? "Your assessment is complete." : feedback.score < 7 ? "We’ll move to the next topic and keep this one in your study plan." : question?.topic === feedback.question.topic ? "Ready for a slightly deeper question?" : "Next, we’ll start with the basics of another topic."}</p><button type="button" className="button button-primary" disabled={busy} onClick={() => { setAcknowledged(feedback.question.id); setError(null); }}>{assessment.status === "completed" ? "See my result" : "Continue"} →</button></div></>
          : question ? <section className="qa-question" key={question.id}><div className="qa-question-meta"><span>{question.type === "single" ? "Choose one answer" : "Select all correct answers"}</span><span>Complexity {question.complexity}/10</span></div><form onSubmit={(e) => { e.preventDefault(); mutate({ action: "answer", questionId: question.id, selected }); }}><fieldset disabled={busy}><legend>{question.prompt}</legend><div className="qa-options">{question.options.map((option, i) => <label key={option.id} className={selected.includes(option.id) ? "selected" : ""}><input type={question.type === "single" ? "radio" : "checkbox"} name="answer" value={option.id} checked={selected.includes(option.id)} onChange={(e) => setSelected(question.type === "single" ? [option.id] : e.target.checked ? [...selected, option.id] : selected.filter((id) => id !== option.id))} /><span className="qa-option-letter" aria-hidden="true">{String.fromCharCode(65 + i)}</span><span>{option.text}</span></label>)}</div></fieldset><div className="qa-question-source"><div className="qa-tags">{question.tags.map((tag) => <span key={tag}>{tag}</span>)}</div><p>Source: <a href={question.source.url} target="_blank" rel="noreferrer">{question.source.title} ↗</a></p>{question.companyContexts.map((context) => <p key={context.company + context.role}><b>{context.company} — {context.role} interview question</b><br /><a href={context.source.url} target="_blank" rel="noreferrer">Source: {context.source.title} ↗</a></p>)}</div><div className="qa-question-submit"><p>{question.type === "multiple" ? "Partial credit for correct selections. Incorrect selections reduce the score; selecting every option earns 0." : "A correct answer earns 10 points."}</p><button type="submit" className="button button-primary" disabled={busy || !selected.length}>{busy ? "Saving…" : "Check answer"} →</button></div></form></section> : null}
          {assessment.status === "active" && assessment.answered > 0 ? <div className="qa-finish-early">{finishPrompt ? <><p>Finish with {assessment.answered} answered questions? Your result will identify topics not yet assessed.</p><button disabled={busy} type="button" className="button button-secondary" onClick={() => mutate({ action: "finish" })}>Finish and see result</button><button type="button" disabled={busy} className="qa-text-button" onClick={() => setFinishPrompt(false)}>Keep going</button></> : <button className="qa-text-button" type="button" disabled={busy} onClick={() => setFinishPrompt(true)}>Finish assessment early</button>}</div> : null}
        </> : <>
          <section className="qa-result-hero"><div><p className="eyebrow">Overall score</p><strong className="qa-total-score">{assessment.percent ?? 0}<span>%</span></strong><p className="qa-total-points">{assessment.earned} / {assessment.possible} points · {assessment.answered} answers</p></div><div><span className="qa-result-level">{assessment.level} scope</span><h2>{assessment.percent !== null && assessment.percent >= 80 ? "Keep building on your strengths." : "Your next steps are in focus."}</h2><p>{assessment.summary}</p>{assessment.finishedEarly ? <p><b>Finished early.</b> Only submitted answers count toward your score.</p> : null}<p className="qa-muted">Adaptive assessments cover different questions. Percentages describe this attempt and should not be used to rank students.</p></div></section>
          <section className="qa-results"><h2>Your strengths & next steps</h2><p>Difficulty reached is the highest complexity answered with at least 7/10. A short sample cannot establish mastery of a whole topic.</p><div className="qa-table-wrap"><table><thead><tr><th scope="col">Topic</th><th scope="col">Points</th><th scope="col">Difficulty reached</th><th scope="col">Next step</th></tr></thead><tbody>{assessment.results.map((r) => <tr key={r.id}><th scope="row">{r.title}<small>{r.answered} answered</small></th><td>{r.possible ? `${r.earned} / ${r.possible}` : "—"}</td><td>{r.highestPassed === null ? "—" : `${r.highestPassed}/10`}</td><td><span className={`qa-status ${r.status}`}>{r.status === "strong" ? "Strength in this sample" : r.status === "developing" ? "Keep practicing" : r.status === "revisit" ? "Revisit the foundations" : "Not assessed"}</span></td></tr>)}</tbody></table></div></section>
          <section className="qa-study"><div className="qa-section-heading"><div><p className="eyebrow">Make your next session count</p><h2>Your study plan</h2></div></div><div className="qa-study-grid">{assessment.results.filter((r) => r.references.length).map((r) => <article key={r.id}><h3>{r.title}</h3><p>Review the concepts behind the answers you missed.</p><References items={r.references} /></article>)}{assessment.results.every((r) => !r.references.length) ? <article><h3>Ready to broaden your practice?</h3><p>Try additional topics or a higher level when you feel ready.</p><References items={[{ title: "Explore the Java engineer roadmap", url: roadmapUrl }]} /></article> : null}</div></section>
          <section className="qa-history"><h2>Review your answers</h2>{assessment.history.map((answer, i) => <details key={answer.question.id}><summary><span>{i + 1}. {answer.question.prompt}</span><b>{answer.score}/10</b></summary><Feedback feedback={answer} busy={busy} onRate={(input) => mutate({ action: "feedback", ...input })} /></details>)}</section>
          <div className="qa-result-actions"><button type="button" className="button button-primary" onClick={newAssessment}>Start another assessment →</button><button type="button" className="button button-secondary" onClick={() => window.print()}>Print / save result</button></div>
        </>}
      </> : null}
    </main><footer className="qa-footer"><span>Interview Prep · Learn with clarity.</span><span>Java Q&A · General knowledge first</span></footer>
  </div>;
}
