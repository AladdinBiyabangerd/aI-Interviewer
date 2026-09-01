"use client";

import { useState } from "react";

type View = "dashboard" | "setup" | "profile" | "interview" | "report";

const interviewQuestions = [
  {
    label: "Technical depth",
    question:
      "How would you investigate and optimize an API whose latency increases under heavy traffic?",
    hint: "Think systematically: measurement, bottleneck, solution, and outcome.",
  },
  {
    label: "Problem solving",
    question:
      "A critical production service has failed unexpectedly. What would you do in the first 30 minutes?",
    hint: "Show how you prioritize, communicate, and approach root-cause analysis.",
  },
  {
    label: "Leadership",
    question:
      "Tell me about a time you resolved a disagreement over a technical decision within your team.",
    hint: "Use the STAR structure: situation, task, action, and result.",
  },
];

const navItems: { id: View; label: string; glyph: string }[] = [
  { id: "dashboard", label: "Dashboard", glyph: "⌂" },
  { id: "setup", label: "New preparation", glyph: "+" },
  { id: "profile", label: "AI profile", glyph: "◫" },
  { id: "interview", label: "Interview", glyph: "◎" },
  { id: "report", label: "Reports", glyph: "↗" },
];

function Brand() {
  return (
    <div className="brand" aria-label="Interview AI">
      <span className="brand-mark" aria-hidden="true">I</span>
      <span><strong>Interview</strong><small>AI preparation platform</small></span>
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
          <span className="tiny-label">BETA ACCESS</span><strong>Professional plan</strong>
          <p>7 practice sessions left this month</p><div className="plan-progress"><span /></div>
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
    profile: "AI candidate profile",
    interview: "Interview simulation",
    report: "Performance report",
  };
  return (
    <header className="topbar">
      <div className="mobile-brand"><Brand /></div>
      <div><span className="breadcrumb">Workspace /</span> {titles[view]}</div>
      <div className="top-actions"><span className="demo-pill"><i /> Demo mode</span><button className="round-button" aria-label="Notifications" type="button">•</button></div>
    </header>
  );
}

function Dashboard({ onStart }: { onStart: () => void }) {
  return (
    <div className="screen dashboard-screen">
      <section className="hero-grid">
        <div className="hero-copy">
          <span className="eyebrow"><i /> Your personal AI interview coach</span>
          <h1>Prepare for the interview.<br /><em>With confidence.</em></h1>
          <p>Tailored questions based on your resume and target role, a realistic simulation, and a focused improvement plan.</p>
          <div className="hero-actions"><button className="primary-button" onClick={onStart} type="button">Start demo interview <span>→</span></button><span className="privacy-note"><b>✓</b> No card required</span></div>
          <div className="hero-proof"><div className="avatar-stack"><span>AY</span><span>NM</span><span>SA</span><span>+</span></div><p><strong>1,200+</strong> candidates already feel more prepared</p></div>
        </div>
        <div className="session-visual">
          <div className="visual-orbit orbit-one" /><div className="visual-orbit orbit-two" />
          <div className="visual-topline"><span><i /> Next session</span><b>Today, 6:30 PM</b></div>
          <div className="interviewer-orb"><span>AI</span><i /></div>
          <span className="visual-kicker">TECHNICAL INTERVIEW</span><h2>Senior Backend Developer</h2><p>Kapital Bank · 45 min · 12 questions</p>
          <div className="question-preview"><span>01</span><p>“How do you protect system performance under heavy load?”</p></div>
          <button onClick={onStart} type="button">Open session <span>↗</span></button>
        </div>
      </section>
      <section className="metric-strip" aria-label="Preparation metrics">
        <div><span className="metric-icon lime">↗</span><p>Readiness score<strong>82%</strong><small>+12% this week</small></p></div>
        <div><span className="metric-icon mint">✓</span><p>Completed practice<strong>8</strong><small>3 sessions this week</small></p></div>
        <div><span className="metric-icon sand">◎</span><p>Average answer quality<strong>7.8</strong><small>out of 10</small></p></div>
        <div><span className="metric-icon blue">◷</span><p>Practice time<strong>4.2 hours</strong><small>Focus: system design</small></p></div>
      </section>
      <section className="lower-grid">
        <div className="panel recent-panel">
          <div className="panel-heading"><div><span className="section-kicker">RECENT ACTIVITY</span><h3>Interview sessions</h3></div><button type="button">View all →</button></div>
          <div className="session-row"><span className="company-logo kapital">K</span><p><strong>Kapital Bank</strong><small>Senior Backend Developer · Technical</small></p><time>Aug 29, 16:40</time><b className="score good">8.4</b></div>
          <div className="session-row"><span className="company-logo pasha">P</span><p><strong>PASHA Technology</strong><small>Software Engineer · HR screening</small></p><time>Aug 27, 11:20</time><b className="score mid">7.6</b></div>
          <div className="session-row"><span className="company-logo abb">A</span><p><strong>ABB</strong><small>Backend Engineer · System design</small></p><time>Aug 24, 19:10</time><b className="score good">8.1</b></div>
        </div>
        <div className="panel focus-panel">
          <div className="panel-heading"><div><span className="section-kicker">AI RECOMMENDATION</span><h3>Focus this week</h3></div><span className="trend">+18%</span></div>
          <div className="focus-chart"><div className="chart-ring"><strong>68%</strong><small>completed</small></div><ul><li><i className="dot green" />System design <b>82%</b></li><li><i className="dot lime-dot" />Behavioral <b>64%</b></li><li><i className="dot gray" />SQL & data <b>57%</b></li></ul></div>
          <p className="focus-tip"><b>For today:</b> Practice two questions about cache invalidation.</p>
        </div>
      </section>
    </div>
  );
}

function StepHeader({ current }: { current: number }) {
  const steps = ["Details", "AI profile", "Interview", "Report"];
  return <div className="stepper">{steps.map((step, index) => <div className={index + 1 <= current ? "step active" : "step"} key={step}><span>{index + 1 < current ? "✓" : index + 1}</span><b>{step}</b>{index < steps.length - 1 && <i />}</div>)}</div>;
}

function Setup({ onAnalyze }: { onAnalyze: () => void }) {
  const [company, setCompany] = useState("Kapital Bank");
  const [role, setRole] = useState("Senior Backend Developer");
  const [analyzing, setAnalyzing] = useState(false);
  function analyze() { setAnalyzing(true); window.setTimeout(onAnalyze, 900); }
  return (
    <div className="screen flow-screen">
      <StepHeader current={1} />
      <div className="flow-heading"><span className="eyebrow"><i /> Ready in 2 minutes</span><h1>Tell us about your target</h1><p>AI will tailor the questions and evaluation to this context.</p></div>
      <div className="setup-grid">
        <section className="form-card">
          <div className="card-number">01</div><div><span className="section-kicker">INTERVIEW CONTEXT</span><h2>Which role are you preparing for?</h2></div>
          <label>Company<input value={company} onChange={(event) => setCompany(event.target.value)} /></label>
          <label>Role<input value={role} onChange={(event) => setRole(event.target.value)} /></label>
          <div className="field-pair"><label>Level<select defaultValue="senior"><option value="mid">Mid-level</option><option value="senior">Senior</option><option value="lead">Lead</option></select></label><label>Stage<select defaultValue="technical"><option value="hr">HR screening</option><option value="technical">Technical interview</option><option value="system">System design</option></select></label></div>
          <label>Interview language<div className="segmented"><button className="selected" type="button">English</button><button type="button">German</button><button type="button">Spanish</button></div></label>
        </section>
        <section className="form-card upload-section">
          <div className="card-number">02</div><div><span className="section-kicker">DOCUMENTS</span><h2>Add context for the AI</h2></div>
          <div className="file-card ready"><span className="file-type">PDF</span><p><strong>Elvin_Mammadov_CV.pdf</strong><small>1.8 MB · Resume read successfully</small></p><b>✓</b></div>
          <div className="file-card ready"><span className="file-type jd">JD</span><p><strong>Senior_Backend_JD.pdf</strong><small>846 KB · 12 requirements found</small></p><b>✓</b></div>
          <button className="upload-more" type="button"><span>+</span> Add another document</button>
          <div className="security-copy"><b>Your personal data is protected</b><p>Documents are used only for this preparation and are never shared without your permission.</p></div>
        </section>
      </div>
      <div className="flow-footer"><p><b>Ready:</b> {company} · {role}</p><button className="primary-button" disabled={analyzing} onClick={analyze} type="button">{analyzing ? <><span className="spinner" /> AI is analyzing...</> : <>Start AI analysis <span>→</span></>}</button></div>
    </div>
  );
}

function ProfileView({ onStart }: { onStart: () => void }) {
  return (
    <div className="screen flow-screen">
      <StepHeader current={2} />
      <section className="profile-hero">
        <div><span className="eyebrow"><i /> Analysis complete</span><h1>Your profile is <em>strong</em> for this role.</h1><p>We compared your resume with 12 core requirements. The AI built an interview plan around your strongest evidence and most important gaps.</p></div>
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

function Interview({ onFinish }: { onFinish: () => void }) {
  const [questionIndex, setQuestionIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const current = interviewQuestions[questionIndex];
  function next() { if (questionIndex === interviewQuestions.length - 1) onFinish(); else { setQuestionIndex((value) => value + 1); setAnswer(""); } }
  return (
    <div className="screen interview-screen">
      <StepHeader current={3} />
      <div className="interview-layout">
        <section className="interview-stage">
          <div className="stage-head"><span className="live-badge"><i /> LIVE SIMULATION</span><span>Question {questionIndex + 1} / {interviewQuestions.length}</span><time>12:48</time></div>
          <div className="ai-persona"><div className="persona-face"><span>AI</span><i /></div><p><strong>Ava</strong><small>Technical interviewer</small></p></div>
          <div className="question-card"><span>{current.label}</span><h1>{current.question}</h1><p>{current.hint}</p></div>
          <label className="answer-box"><span>Your answer</span><textarea value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder="Write your answer here..." /><div><small>{answer.length} characters</small><button disabled={answer.trim().length < 20} onClick={next} type="button">{questionIndex === interviewQuestions.length - 1 ? "Generate report" : "Submit answer"} <span>→</span></button></div></label>
        </section>
        <aside className="interview-notes">
          <span className="section-kicker">SESSION PLAN</span><h3>Senior Backend Developer</h3><p>Kapital Bank · Technical stage</p>
          <div className="mini-progress"><span style={{ width: `${((questionIndex + 1) / interviewQuestions.length) * 100}%` }} /></div>
          <ul><li className="done"><span>✓</span><p>Introduction<small>Completed</small></p></li><li className="active"><span>02</span><p>Technical depth<small>In progress</small></p></li><li><span>03</span><p>System design<small>Up next</small></p></li><li><span>04</span><p>Your questions<small>Later</small></p></li></ul>
          <div className="simulation-note"><strong>Simulation mode</strong><p>Just like a real interview, your score stays hidden while you answer. Detailed feedback appears at the end.</p></div>
        </aside>
      </div>
    </div>
  );
}

function Report({ onRestart }: { onRestart: () => void }) {
  return (
    <div className="screen flow-screen report-screen">
      <StepHeader current={4} />
      <section className="report-hero"><div><span className="eyebrow"><i /> Session complete</span><h1>Strong result, Elvin.</h1><p>Your technical foundation is solid. More specific outcomes and clearer trade-off explanations will take your answers to the next level.</p></div><div className="report-score"><div className="score-ring"><span><strong>82</strong><small>/ 100</small></span></div><p>Interview readiness<b>Ready for interviews</b></p></div></section>
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
  return (
    <main className="app-shell">
      <Sidebar view={view} onNavigate={setView} />
      <div className="app-main"><Topbar view={view} />
        {view === "dashboard" && <Dashboard onStart={() => setView("setup")} />}
        {view === "setup" && <Setup onAnalyze={() => setView("profile")} />}
        {view === "profile" && <ProfileView onStart={() => setView("interview")} />}
        {view === "interview" && <Interview onFinish={() => setView("report")} />}
        {view === "report" && <Report onRestart={() => setView("setup")} />}
      </div>
    </main>
  );
}
