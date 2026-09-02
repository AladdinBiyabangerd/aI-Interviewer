"use client";

import { useState } from "react";

type View = "dashboard" | "setup" | "profile" | "interview" | "report";

type PreparationContext = {
  company: string;
  role: string;
};

const defaultContext: PreparationContext = {
  company: "Kapital Bank",
  role: "Senior Backend Developer",
};

const interviewQuestions = [
  {
    label: "Technical depth",
    question:
      "How would you investigate and optimize an API whose latency increases under heavy traffic?",
    hint: "Think systematically: measurement, bottleneck, solution, and outcome.",
    sampleAnswer:
      "I would start with latency percentiles, traces, and saturation metrics to isolate the bottleneck. Then I would reproduce the traffic pattern, test the smallest safe change, and compare p95 latency and error rate before a gradual rollout.",
  },
  {
    label: "Problem solving",
    question:
      "A critical production service has failed unexpectedly. What would you do in the first 30 minutes?",
    hint: "Show how you prioritize, communicate, and approach root-cause analysis.",
    sampleAnswer:
      "First I would establish incident ownership, protect customers with a rollback or traffic shift, and communicate a concise status. In parallel, I would use recent deploys, logs, traces, and dependency health to narrow the cause before testing a recovery action.",
  },
  {
    label: "Leadership",
    question:
      "Tell me about a time you resolved a disagreement over a technical decision within your team.",
    hint: "Use the STAR structure: situation, task, action, and result.",
    sampleAnswer:
      "During a payment-service redesign, two engineers disagreed about introducing a new queue. I documented the failure modes, facilitated a short design review, and proposed a load test. The evidence helped us choose the simpler option and ship without delaying the release.",
  },
];

const navItems: { id: View; label: string; glyph: string }[] = [
  { id: "dashboard", label: "Overview", glyph: "01" },
  { id: "setup", label: "New preparation", glyph: "02" },
  { id: "profile", label: "Candidate brief", glyph: "03" },
  { id: "interview", label: "Practice room", glyph: "04" },
  { id: "report", label: "Review", glyph: "05" },
];

function Brand() {
  return (
    <div className="brand" aria-label="Interview OS">
      <span className="brand-mark" aria-hidden="true">IO</span>
      <span><strong>InterviewOS</strong><small>Preparation workspace</small></span>
    </div>
  );
}

function Sidebar({ view, onNavigate }: { view: View; onNavigate: (view: View) => void }) {
  return (
    <aside className="sidebar">
      <Brand />
      <nav className="side-nav" aria-label="Primary navigation">
        <p className="nav-label">Workspace</p>
        {navItems.map((item) => (
          <button className={view === item.id ? "nav-item active" : "nav-item"} key={item.id} onClick={() => onNavigate(item.id)} type="button">
            <span aria-hidden="true">{item.glyph}</span>{item.label}
          </button>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <div className="plan-card">
          <span className="tiny-label">DEMO WORKSPACE</span><strong>Product walkthrough</strong>
          <p>All information shown here is synthetic.</p><div className="plan-progress"><span /></div>
        </div>
        <button className="profile-chip" type="button">
          <span className="avatar">EM</span><span><strong>Elvin Mammadov</strong><small>Senior Backend</small></span><b aria-hidden="true">•••</b>
        </button>
      </div>
    </aside>
  );
}

function Topbar({ view }: { view: View }) {
  const titles: Record<View, string> = {
    dashboard: "Preparation hub",
    setup: "New preparation",
    profile: "Candidate brief",
    interview: "Practice session",
    report: "Performance report",
  };
  return (
    <header className="topbar">
      <div className="mobile-brand"><Brand /></div>
      <div><span className="breadcrumb">Workspace /</span> {titles[view]}</div>
      <div className="top-actions"><span className="demo-pill"><i /> Guided demo</span><button className="round-button" aria-label="Help" type="button">?</button></div>
    </header>
  );
}

function Dashboard({ onStart }: { onStart: () => void }) {
  return (
    <div className="screen dashboard-screen">
      <section className="hero-grid">
        <div className="hero-copy">
          <span className="eyebrow">Structured interview preparation</span>
          <h1>Walk into the interview <em>prepared.</em></h1>
          <p>Turn a resume and job description into a focused practice session, evidence-based feedback, and a clear plan for improvement.</p>
          <div className="hero-actions"><button className="primary-button" onClick={onStart} type="button">Start product walkthrough <span>→</span></button><span className="privacy-note">Takes about 3 minutes</span></div>
          <div className="hero-proof"><span>Resume evidence</span><span>Role-specific questions</span><span>Detailed review</span></div>
        </div>
        <div className="session-visual">
          <div className="visual-topline"><span>INTERVIEW BRIEF</span><b>Ready to practise</b></div>
          <div className="brief-company"><span>KB</span><p><small>Target company</small><strong>Kapital Bank</strong></p></div>
          <span className="visual-kicker">TECHNICAL INTERVIEW</span><h2>Senior Backend Developer</h2><p>45 minutes · 12 tailored questions</p>
          <div className="brief-agenda"><div><span>01</span><p><strong>Technical depth</strong><small>Systems, APIs and data</small></p><b>20 min</b></div><div><span>02</span><p><strong>Decision making</strong><small>Trade-offs and ownership</small></p><b>15 min</b></div><div><span>03</span><p><strong>Your questions</strong><small>Close with confidence</small></p><b>10 min</b></div></div>
          <button onClick={onStart} type="button">Open preparation <span>→</span></button>
        </div>
      </section>
      <section className="metric-strip" aria-label="Preparation metrics">
        <div><span className="metric-icon">01</span><p>Readiness score<strong>82%</strong><small>Up 12% this week</small></p></div>
        <div><span className="metric-icon">02</span><p>Completed practice<strong>8</strong><small>3 sessions this week</small></p></div>
        <div><span className="metric-icon">03</span><p>Answer quality<strong>7.8</strong><small>Average out of 10</small></p></div>
        <div><span className="metric-icon">04</span><p>Practice time<strong>4.2 h</strong><small>Focus: system design</small></p></div>
      </section>
      <section className="lower-grid">
        <div className="panel recent-panel">
          <div className="panel-heading"><div><span className="section-kicker">RECENT ACTIVITY</span><h3>Interview sessions</h3></div><button type="button">View all →</button></div>
          <div className="session-row"><span className="company-logo kapital">K</span><p><strong>Kapital Bank</strong><small>Senior Backend Developer · Technical</small></p><time>Aug 29, 16:40</time><b className="score good">8.4</b></div>
          <div className="session-row"><span className="company-logo pasha">P</span><p><strong>PASHA Technology</strong><small>Software Engineer · HR screening</small></p><time>Aug 27, 11:20</time><b className="score mid">7.6</b></div>
          <div className="session-row"><span className="company-logo abb">A</span><p><strong>ABB</strong><small>Backend Engineer · System design</small></p><time>Aug 24, 19:10</time><b className="score good">8.1</b></div>
        </div>
        <div className="panel focus-panel">
          <div className="panel-heading"><div><span className="section-kicker">RECOMMENDED PRACTICE</span><h3>Focus this week</h3></div><span className="trend">68% complete</span></div>
          <div className="focus-chart"><div className="chart-ring"><strong>68%</strong><small>completed</small></div><ul><li><i className="dot primary-dot" />System design <b>82%</b></li><li><i className="dot warm-dot" />Behavioral <b>64%</b></li><li><i className="dot gray" />SQL & data <b>57%</b></li></ul></div>
          <p className="focus-tip"><b>For today:</b> Practice two questions about cache invalidation.</p>
        </div>
      </section>
    </div>
  );
}

function StepHeader({ current }: { current: number }) {
  const steps = ["Details", "Candidate brief", "Practice", "Review"];
  return <div className="stepper">{steps.map((step, index) => <div className={index + 1 <= current ? "step active" : "step"} key={step}><span>{index + 1 < current ? "✓" : index + 1}</span><b>{step}</b>{index < steps.length - 1 && <i />}</div>)}</div>;
}

function Setup({ context, onAnalyze }: { context: PreparationContext; onAnalyze: (context: PreparationContext) => void }) {
  const [company, setCompany] = useState(context.company);
  const [role, setRole] = useState(context.role);
  const [analyzing, setAnalyzing] = useState(false);
  const isReady = company.trim().length > 1 && role.trim().length > 1;
  function analyze() {
    if (!isReady) return;
    setAnalyzing(true);
    window.setTimeout(
      () => onAnalyze({ company: company.trim(), role: role.trim() }),
      900,
    );
  }
  return (
    <div className="screen flow-screen">
      <StepHeader current={1} />
      <div className="flow-heading"><span className="eyebrow">Preparation details</span><h1>Define the interview</h1><p>We use the role and supporting material to build a relevant practice session.</p></div>
      <div className="setup-grid">
        <section className="form-card">
          <div className="card-number">01</div><div><span className="section-kicker">INTERVIEW CONTEXT</span><h2>Which role are you preparing for?</h2></div>
          <label>Company<input value={company} onChange={(event) => setCompany(event.target.value)} /></label>
          <label>Role<input value={role} onChange={(event) => setRole(event.target.value)} /></label>
          <div className="field-pair"><label>Level<select defaultValue="senior"><option value="mid">Mid-level</option><option value="senior">Senior</option><option value="lead">Lead</option></select></label><label>Stage<select defaultValue="technical"><option value="hr">HR screening</option><option value="technical">Technical interview</option><option value="system">System design</option></select></label></div>
          <label>Interview language<div className="segmented single"><button aria-pressed="true" className="selected" type="button">English demo</button></div></label>
        </section>
        <section className="form-card upload-section">
          <div className="card-number">02</div><div><span className="section-kicker">DOCUMENTS</span><h2>Add supporting material</h2></div>
          <div className="file-card ready"><span className="file-type">PDF</span><p><strong>Elvin_Mammadov_CV.pdf</strong><small>1.8 MB · Resume read successfully</small></p><b>✓</b></div>
          <div className="file-card ready"><span className="file-type jd">JD</span><p><strong>Senior_Backend_JD.pdf</strong><small>846 KB · 12 requirements found</small></p><b>✓</b></div>
          <div className="demo-data-note"><span>DEMO DATA</span><p>Synthetic documents are preloaded so the full product journey can be presented without exposing candidate data.</p></div>
          <div className="security-copy"><b>Your personal data is protected</b><p>Documents are used only for this preparation and are never shared without your permission.</p></div>
        </section>
      </div>
      <div className="flow-footer" aria-live="polite"><p><b>Ready:</b> {company || "Add a company"} · {role || "Add a role"}</p><button className="primary-button" disabled={analyzing || !isReady} onClick={analyze} type="button">{analyzing ? <><span className="spinner" /> Reviewing materials...</> : <>Build interview plan <span>→</span></>}</button></div>
    </div>
  );
}

function ProfileView({ context, onStart }: { context: PreparationContext; onStart: () => void }) {
  return (
    <div className="screen flow-screen">
      <StepHeader current={2} />
      <section className="profile-hero">
        <div><span className="eyebrow">Candidate brief complete</span><h1>Your experience aligns well with this role.</h1><p>We compared your resume with 12 core requirements for {context.role} at {context.company}. Your session focuses on the strongest evidence and the gaps most likely to come up.</p></div>
        <div className="match-score"><div><strong>86</strong><span>%</span></div><p>Role match<small>High match</small></p></div>
      </section>
      <div className="profile-grid">
        <section className="panel skill-panel"><div className="panel-heading"><div><span className="section-kicker">STRENGTHS</span><h3>Skills confirmed for this role</h3></div><span className="count-pill">8 matches</span></div><div className="skills"><span>Python <b>Strong</b></span><span>FastAPI <b>Strong</b></span><span>PostgreSQL <b>Strong</b></span><span>Docker <b>Good</b></span><span>Microservices <b>Good</b></span><span>CI/CD <b>Good</b></span></div><div className="evidence-box"><span>RESUME EVIDENCE</span><p>“Designed 12 microservices for a payment platform and optimized the system for high traffic...”</p></div></section>
        <section className="panel gap-panel"><div className="panel-heading"><div><span className="section-kicker">GROWTH AREAS</span><h3>Gaps to explore in the interview</h3></div></div><div className="gap-item"><span>01</span><p><strong>System design trade-offs</strong><small>The resume does not show measurable outcomes from scaling decisions</small></p><b>Priority</b></div><div className="gap-item"><span>02</span><p><strong>Team leadership</strong><small>Mentoring is evident, but there is no conflict-resolution example</small></p><b>Medium</b></div><div className="gap-item"><span>03</span><p><strong>Cloud infrastructure</strong><small>The role asks for AWS, but the resume provides limited evidence</small></p><b>Medium</b></div></section>
        <section className="panel plan-panel wide"><div><span className="section-kicker">PERSONAL INTERVIEW PLAN</span><h3>45 min · 4 stages · 12 questions</h3><p>The question sequence is tailored to your profile and the role’s priorities.</p></div><div className="plan-stages"><span><b>01</b>Introduction<small>5 min</small></span><span><b>02</b>Technical depth<small>20 min</small></span><span><b>03</b>System design<small>15 min</small></span><span><b>04</b>Your questions<small>5 min</small></span></div><button className="primary-button" onClick={onStart} type="button">Start interview <span>→</span></button></section>
      </div>
    </div>
  );
}

function Interview({ context, onFinish }: { context: PreparationContext; onFinish: () => void }) {
  const [questionIndex, setQuestionIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const current = interviewQuestions[questionIndex];
  function next() { if (questionIndex === interviewQuestions.length - 1) onFinish(); else { setQuestionIndex((value) => value + 1); setAnswer(""); } }
  return (
    <div className="screen interview-screen">
      <StepHeader current={3} />
      <div className="interview-layout">
        <section className="interview-stage">
          <div className="stage-head"><span className="live-badge">PRACTICE SESSION</span><span>Question {questionIndex + 1} / {interviewQuestions.length}</span><time>12:48</time></div>
          <div className="ai-persona"><div className="persona-face"><span>A</span></div><p><strong>Ava</strong><small>Interview coach</small></p></div>
          <div className="question-card"><span>{current.label}</span><h1>{current.question}</h1><p>{current.hint}</p></div>
          <label className="answer-box"><span>Your answer</span><textarea maxLength={1500} value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder="Write your answer here or use the guided demo answer..." /><div className="answer-footer"><small>{answer.length} / 1,500 characters</small><div><button className="text-button" onClick={() => setAnswer(current.sampleAnswer)} type="button">Use demo answer</button><button disabled={answer.trim().length < 20} onClick={next} type="button">{questionIndex === interviewQuestions.length - 1 ? "Generate report" : "Submit answer"} <span>→</span></button></div></div></label>
        </section>
        <aside className="interview-notes">
          <span className="section-kicker">SESSION PLAN</span><h3>{context.role}</h3><p>{context.company} · Technical stage</p>
          <div className="mini-progress"><span style={{ width: `${((questionIndex + 1) / interviewQuestions.length) * 100}%` }} /></div>
          <ul><li className="done"><span>✓</span><p>Introduction<small>Completed</small></p></li><li className="active"><span>02</span><p>Technical depth<small>In progress</small></p></li><li><span>03</span><p>System design<small>Up next</small></p></li><li><span>04</span><p>Your questions<small>Later</small></p></li></ul>
          <div className="simulation-note"><strong>Simulation mode</strong><p>Just like a real interview, your score stays hidden while you answer. Detailed feedback appears at the end.</p></div>
        </aside>
      </div>
    </div>
  );
}

function Report({ context, onRestart }: { context: PreparationContext; onRestart: () => void }) {
  return (
    <div className="screen flow-screen report-screen">
      <StepHeader current={4} />
      <section className="report-hero"><div><span className="eyebrow"><i /> Guided demo complete</span><h1>Strong result, Elvin.</h1><p>Your {context.role} simulation for {context.company} shows a solid technical foundation. More specific outcomes and clearer trade-off explanations will take your answers to the next level.</p></div><div className="report-score"><div className="score-ring"><span><strong>82</strong><small>/ 100</small></span></div><p>Demo readiness score<b>Ready for interviews</b></p></div></section>
      <section className="report-metrics"><div><span>Technical depth</span><strong>8.6</strong><i><b style={{ width: "86%" }} /></i></div><div><span>Structure and clarity</span><strong>7.8</strong><i><b style={{ width: "78%" }} /></i></div><div><span>Example quality</span><strong>7.2</strong><i><b style={{ width: "72%" }} /></i></div><div><span>Communication</span><strong>8.4</strong><i><b style={{ width: "84%" }} /></i></div></section>
      <div className="report-grid">
        <section className="panel feedback-card positive"><span className="feedback-icon">✓</span><div><span className="section-kicker">STRENGTHS</span><h3>What you did well</h3><ul><li>Broke the problem into measurable stages</li><li>Prioritized observability and database bottlenecks correctly</li><li>Took a practical approach to team communication</li></ul></div></section>
        <section className="panel feedback-card improve"><span className="feedback-icon">↗</span><div><span className="section-kicker">OPPORTUNITY</span><h3>What to strengthen</h3><ul><li>Connect each answer to a measurable business outcome</li><li>Compare alternative solutions and their trade-offs explicitly</li><li>Make your personal contribution clearer in leadership examples</li></ul></div></section>
        <section className="panel action-plan wide"><div><span className="section-kicker">YOUR 7-DAY PLAN</span><h3>Before your next interview</h3></div><div className="action-list"><span><b>01</b><p><strong>System design drill</strong><small>Rate limiter and payment system · 25 min</small></p><em>Today</em></span><span><b>02</b><p><strong>STAR answer practice</strong><small>2 leadership examples · 20 min</small></p><em>Tomorrow</em></span><span><b>03</b><p><strong>Final simulation</strong><small>Full technical interview · 45 min</small></p><em>In 5 days</em></span></div><button className="primary-button" onClick={onRestart} type="button">Create new practice <span>→</span></button></section>
      </div>
    </div>
  );
}

export default function Home() {
  const [view, setView] = useState<View>("dashboard");
  const [context, setContext] = useState<PreparationContext>(defaultContext);
  function completeAnalysis(nextContext: PreparationContext) {
    setContext(nextContext);
    setView("profile");
  }
  return (
    <main className="app-shell">
      <Sidebar view={view} onNavigate={setView} />
      <div className="app-main"><Topbar view={view} />
        {view === "dashboard" && <Dashboard onStart={() => setView("setup")} />}
        {view === "setup" && <Setup context={context} onAnalyze={completeAnalysis} />}
        {view === "profile" && <ProfileView context={context} onStart={() => setView("interview")} />}
        {view === "interview" && <Interview context={context} onFinish={() => setView("report")} />}
        {view === "report" && <Report context={context} onRestart={() => setView("setup")} />}
      </div>
    </main>
  );
}
