"use client";

import { useState } from "react";

type View = "home" | "setup" | "profile" | "interview" | "report";
type Scenario = "Technical" | "Behavioral" | "HR screening";

type PreparationContext = {
  company: string;
  role: string;
  scenario: Scenario;
};

const defaultContext: PreparationContext = {
  company: "Kapital Bank",
  role: "Senior Backend Developer",
  scenario: "Technical",
};

const interviewQuestions = [
  {
    label: "Technical depth",
    question:
      "How would you investigate and improve an API whose latency increases under heavy traffic?",
    hint: "Explain what you would measure first, how you would isolate the cause, and how you would validate the result.",
    sampleAnswer:
      "I would begin with latency percentiles, traces, and saturation metrics to identify where requests slow down. I would reproduce the traffic pattern, test the smallest safe change, and compare p95 latency and error rate before a gradual rollout.",
  },
  {
    label: "Problem solving",
    question:
      "A critical production service has failed unexpectedly. What would you do in the first 30 minutes?",
    hint: "Show how you protect customers, coordinate the response, and narrow the root cause.",
    sampleAnswer:
      "I would assign incident ownership, protect customers with a rollback or traffic shift, and communicate a clear status. In parallel, I would review recent deployments, logs, traces, and dependency health before testing a recovery action.",
  },
  {
    label: "Leadership",
    question:
      "Tell me about a time you resolved a disagreement over a technical decision within your team.",
    hint: "Use a concrete situation, your action, and a measurable result.",
    sampleAnswer:
      "During a payment-service redesign, two engineers disagreed about introducing a new queue. I documented the failure modes, facilitated a short design review, and proposed a load test. The evidence helped us choose the simpler option and ship on time.",
  },
];

const flow: { id: Exclude<View, "home">; label: string }[] = [
  { id: "setup", label: "Context" },
  { id: "profile", label: "Brief" },
  { id: "interview", label: "Practice" },
  { id: "report", label: "Feedback" },
];

function Header({ view, onNavigate }: { view: View; onNavigate: (view: View) => void }) {
  return (
    <header className="site-header">
      <div className="header-inner">
        <button className="brand" type="button" onClick={() => onNavigate("home")} aria-label="InterviewOS home">
          <span aria-hidden="true">IO</span>
          InterviewOS
        </button>
        <nav className="flow-nav" aria-label="Demo steps">
          {flow.map((item, index) => (
            <button
              className={view === item.id ? "active" : ""}
              key={item.id}
              onClick={() => onNavigate(item.id)}
              type="button"
            >
              <span>{index + 1}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <span className="ai-label">AI-assisted demo</span>
      </div>
    </header>
  );
}

function PageHeading({ step, title, description }: { step: string; title: string; description: string }) {
  return (
    <div className="page-heading">
      <p className="overline">{step}</p>
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
  );
}

function Home({ onStart }: { onStart: () => void }) {
  return (
    <div className="page home-page">
      <section className="home-hero">
        <p className="overline">AI-assisted interview preparation</p>
        <h1>Practice the questions that matter.</h1>
        <p className="lead">
          Build a focused interview from your target role, practise realistic questions,
          and leave with feedback you can use.
        </p>
        <div className="hero-actions">
          <button className="primary-button" onClick={onStart} type="button">
            Start interview <span aria-hidden="true">→</span>
          </button>
          <span>No account required · 3-minute guided demo</span>
        </div>
      </section>

      <section className="journey" aria-labelledby="journey-title">
        <div>
          <p className="overline">How it works</p>
          <h2 id="journey-title">A clear path from role to feedback.</h2>
        </div>
        <ol>
          <li><span>01</span><div><h3>Set the context</h3><p>Add the role, company, and interview type.</p></div></li>
          <li><span>02</span><div><h3>Practise with AI</h3><p>Answer targeted questions in a quiet workspace.</p></div></li>
          <li><span>03</span><div><h3>Review the evidence</h3><p>See strengths, gaps, and clear next actions.</p></div></li>
        </ol>
      </section>
    </div>
  );
}

function Setup({ context, onContinue }: { context: PreparationContext; onContinue: (value: PreparationContext) => void }) {
  const [company, setCompany] = useState(context.company);
  const [role, setRole] = useState(context.role);
  const [scenario, setScenario] = useState<Scenario>(context.scenario);
  const [loading, setLoading] = useState(false);
  const isReady = company.trim().length > 1 && role.trim().length > 1;

  function submit() {
    if (!isReady) return;
    setLoading(true);
    window.setTimeout(() => {
      onContinue({ company: company.trim(), role: role.trim(), scenario });
    }, 700);
  }

  return (
    <div className="page flow-page">
      <PageHeading
        step="Step 1 of 4 · Context"
        title="Set the interview context."
        description="A few details are enough to make the practice relevant to the role."
      />

      <section className="form-panel" aria-label="Interview context">
        <div className="field-grid">
          <label htmlFor="company">Company<input id="company" value={company} onChange={(event) => setCompany(event.target.value)} /></label>
          <label htmlFor="role">Target role<input id="role" value={role} onChange={(event) => setRole(event.target.value)} /></label>
        </div>

        <fieldset className="scenario-field">
          <legend>Interview scenario</legend>
          <div className="scenario-grid">
            {(["Technical", "Behavioral", "HR screening"] as Scenario[]).map((item) => (
              <button
                aria-pressed={scenario === item}
                className={scenario === item ? "selected" : ""}
                key={item}
                onClick={() => setScenario(item)}
                type="button"
              >
                <span>{item}</span>
                <small>{item === "Technical" ? "Systems and engineering" : item === "Behavioral" ? "Experience and decisions" : "Motivation and fit"}</small>
              </button>
            ))}
          </div>
        </fieldset>

        <div className="source-files" aria-label="Demo source material">
          <div><span aria-hidden="true">CV</span><p><strong>Elvin_Mammadov_CV.pdf</strong><small>Synthetic demo resume</small></p></div>
          <div><span aria-hidden="true">JD</span><p><strong>Senior_Backend_JD.pdf</strong><small>Synthetic job description</small></p></div>
        </div>

        <div className="panel-footer" aria-live="polite">
          <p>Demo files contain no personal data.</p>
          <button className="primary-button" disabled={!isReady || loading} onClick={submit} type="button">
            {loading ? "Preparing brief…" : "Create candidate brief"}<span aria-hidden="true">→</span>
          </button>
        </div>
      </section>
    </div>
  );
}

function Profile({ context, onStart }: { context: PreparationContext; onStart: () => void }) {
  return (
    <div className="page flow-page">
      <PageHeading
        step="Step 2 of 4 · Candidate brief"
        title="Focus on the evidence."
        description={`Your experience is compared with the ${context.role} requirements at ${context.company}.`}
      />

      <section className="brief-summary">
        <div className="match-summary"><strong>86%</strong><span>Role alignment</span></div>
        <div><h2>Strong foundation for a {context.scenario.toLowerCase()} interview.</h2><p>The practice will test technical decisions, measurable outcomes, and communication under pressure.</p></div>
      </section>

      <div className="brief-grid">
        <section className="content-card">
          <p className="overline">Confirmed strengths</p>
          <h2>Evidence to lead with</h2>
          <ul className="plain-list"><li>Python and FastAPI delivery</li><li>PostgreSQL performance work</li><li>Microservice architecture</li></ul>
          <blockquote>“Designed 12 services for a payment platform and improved reliability under peak traffic.”</blockquote>
        </section>
        <section className="content-card">
          <p className="overline">Areas to explore</p>
          <h2>Questions to prepare for</h2>
          <ol className="numbered-list"><li><span>01</span><p><strong>System design trade-offs</strong><small>Explain why one option was better than another.</small></p></li><li><span>02</span><p><strong>Leadership</strong><small>Show your role in resolving disagreement.</small></p></li><li><span>03</span><p><strong>Business impact</strong><small>Connect technical work to measurable outcomes.</small></p></li></ol>
        </section>
      </div>

      <div className="action-row"><p>12 questions · Approximately 45 minutes</p><button className="primary-button" onClick={onStart} type="button">Start practice <span aria-hidden="true">→</span></button></div>
    </div>
  );
}

function Interview({ context, onFinish }: { context: PreparationContext; onFinish: () => void }) {
  const [questionIndex, setQuestionIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const current = interviewQuestions[questionIndex];
  const progress = ((questionIndex + 1) / interviewQuestions.length) * 100;

  function next() {
    if (questionIndex === interviewQuestions.length - 1) {
      onFinish();
      return;
    }
    setQuestionIndex((value) => value + 1);
    setAnswer("");
  }

  return (
    <div className="page interview-page">
      <div className="interview-topline">
        <div><span className="ai-mark" aria-hidden="true">AI</span><p><strong>AI Interview Assistant</strong><small>{context.role} · {context.scenario}</small></p></div>
        <p>Question {questionIndex + 1} of {interviewQuestions.length}</p>
      </div>
      <div className="progress-track" role="progressbar" aria-label="Interview progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress)}><span style={{ width: `${progress}%` }} /></div>

      <main className="dialogue" aria-live="polite">
        <p className="overline">{current.label}</p>
        <h1>{current.question}</h1>
        <p className="question-hint">{current.hint}</p>

        <label htmlFor="answer">Your answer</label>
        <textarea
          id="answer"
          maxLength={1500}
          onChange={(event) => setAnswer(event.target.value)}
          placeholder="Write your answer clearly and use a specific example."
          value={answer}
        />
        <div className="answer-actions">
          <span>{answer.length} / 1,500</span>
          <div><button className="secondary-button" onClick={() => setAnswer(current.sampleAnswer)} type="button">Use demo answer</button><button className="primary-button" disabled={answer.trim().length < 20} onClick={next} type="button">{questionIndex === interviewQuestions.length - 1 ? "Get feedback" : "Next question"}<span aria-hidden="true">→</span></button></div>
        </div>
      </main>
      <p className="speaking-note">Tip: Use short sentences and make your personal contribution explicit.</p>
    </div>
  );
}

const reportMetrics = [
  ["Technical depth", 86],
  ["Structure and clarity", 78],
  ["Example quality", 72],
  ["Communication", 84],
] as const;

function Report({ context, onRestart }: { context: PreparationContext; onRestart: () => void }) {
  return (
    <div className="page flow-page report-page">
      <PageHeading
        step="Step 4 of 4 · Feedback"
        title="A strong result with clear next steps."
        description={`Feedback from the ${context.role} practice for ${context.company}.`}
      />

      <section className="report-summary">
        <div><strong>82</strong><span>Readiness score</span></div>
        <p>You showed solid technical judgment. Stronger metrics and clearer trade-off explanations will make your answers more convincing.</p>
      </section>

      <section className="metrics-card" aria-label="Performance scores">
        {reportMetrics.map(([label, value]) => (
          <div key={label}><p><span>{label}</span><strong>{value}%</strong></p><div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}><span style={{ width: `${value}%` }} /></div></div>
        ))}
      </section>

      <div className="feedback-grid">
        <section className="content-card"><p className="overline">What worked</p><h2>Keep doing this</h2><ul className="plain-list"><li>Break problems into measurable stages</li><li>Protect customers before investigating deeply</li><li>Communicate ownership and next actions</li></ul></section>
        <section className="content-card"><p className="overline">What to improve</p><h2>Make the answer sharper</h2><ul className="plain-list"><li>Add a measurable business result</li><li>Compare the alternatives you rejected</li><li>Clarify your individual contribution</li></ul></section>
      </div>

      <div className="action-row"><p>Recommended next step: one system-design drill</p><button className="primary-button" onClick={onRestart} type="button">Start another practice <span aria-hidden="true">→</span></button></div>
    </div>
  );
}

export default function HomePage() {
  const [view, setView] = useState<View>("home");
  const [context, setContext] = useState<PreparationContext>(defaultContext);

  function completeSetup(value: PreparationContext) {
    setContext(value);
    setView("profile");
  }

  return (
    <>
      <Header view={view} onNavigate={setView} />
      {view === "home" && <Home onStart={() => setView("setup")} />}
      {view === "setup" && <Setup context={context} onContinue={completeSetup} />}
      {view === "profile" && <Profile context={context} onStart={() => setView("interview")} />}
      {view === "interview" && <Interview context={context} onFinish={() => setView("report")} />}
      {view === "report" && <Report context={context} onRestart={() => setView("setup")} />}
    </>
  );
}
