"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { levels, topics, type Level } from "../../lib/assessment";
import type { QuestionInput } from "../../lib/admin-question";
import type { BankQuestion } from "../../lib/server/assessment-bank";
import { Brand } from "../brand";

type Row = { id: string; version: number; status: BankQuestion["status"]; question: BankQuestion; created_at: string };
type Message = { role: "admin" | "assistant"; text: string };
type Editor = QuestionInput;
type Tab = "manual" | "ai";
type Filter = "all" | "draft" | "published" | "retired";

const emptyEditor: Editor = {
  topic: topics[0].id, level: "Junior", complexity: 2,
  prompt: "", options: ["", "", "", ""], correct: ["a"], explanation: "",
  sourceTitle: "", sourceUrl: "", tags: [],
};
const labels = ["A", "B", "C", "D"];
const caps: Record<Level, number> = { Junior: 4, Mid: 7, Senior: 10 };
const errors: Record<string, string> = {
  invalid_question: "Sualı, 4 fərqli variantı, düzgün cavabı, izahı və HTTPS mənbəsini yoxlayın.",
  admin_access_denied: "Admin sessiyası yoxdur. Yenidən daxil olun.",
  ai_rate_limited: "Son bir saat üçün AI limiti dolub. Bir az sonra yenidən yoxlayın.",
  ai_generation_failed: "AI düzgün sual formatı qaytarmadı. Promptu dəqiqləşdirib yenidən yoxlayın.",
  newer_revision_exists: "Bu sualın daha yeni versiyası artıq var. Siyahını yeniləyin.",
  question_not_draft: "Yalnız qaralama suallar nəşr oluna bilər.",
};

function toEditor(question: BankQuestion): Editor {
  return {
    topic: question.topic, level: question.level, complexity: question.complexity,
    prompt: question.prompt, options: question.options.map((option) => option.text),
    correct: question.correct, explanation: question.explanation,
    sourceTitle: question.source.title, sourceUrl: question.source.url,
    tags: question.tags.filter((tag) => tag !== question.topic),
  };
}

async function api<T>(url: string, method = "GET", input?: unknown): Promise<T> {
  const response = await fetch(url, {
    method, cache: "no-store", credentials: "same-origin",
    ...(input === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(errors[result.code] ?? "Əməliyyat tamamlanmadı. Yenidən cəhd edin.");
  return result as T;
}

export default function AdminWorkspace({ name }: { name: string }) {
  const router = useRouter();
  const [rows, setRows] = useState<Row[]>([]);
  const [editor, setEditor] = useState<Editor>(emptyEditor);
  const [tagText, setTagText] = useState("");
  const [editing, setEditing] = useState<Row | null>(null);
  const [tab, setTab] = useState<Tab>("manual");
  const [filter, setFilter] = useState<Filter>("all");
  const [messages, setMessages] = useState<Message[]>([]);
  const [prompt, setPrompt] = useState("");
  const [count, setCount] = useState(2);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const data = await api<{ questions: Row[] }>("/api/admin/questions");
    setRows(data.questions);
  }, []);
  useEffect(() => {
    void api<{ questions: Row[] }>("/api/admin/questions")
      .then((data) => setRows(data.questions), (cause) => setError(cause instanceof Error ? cause.message : "Siyahı yüklənmədi."))
      .finally(() => setLoading(false));
  }, []);

  function change<K extends keyof Editor>(key: K, value: Editor[K]) {
    setEditor((current) => ({ ...current, [key]: value }));
  }

  function changeTopic(value: string) {
    const selected = topics.find((topic) => topic.id === value);
    if (!selected) return;
    setEditor((current) => {
      const level = levels.indexOf(current.level) < levels.indexOf(selected.level) ? selected.level : current.level;
      return { ...current, topic: value, level, complexity: Math.min(current.complexity, caps[level]) };
    });
  }

  function changeLevel(level: Level) {
    setEditor((current) => ({ ...current, level, complexity: Math.min(current.complexity, caps[level]) }));
  }

  function selectRow(row: Row) {
    setEditing(row);
    setEditor(toEditor(row.question));
    setTagText(row.question.tags.filter((tag) => tag !== row.question.topic).join(", "));
    setTab("manual");
    setError(""); setNotice("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const question = { ...editor, tags: tagText.split(",").map((tag) => tag.trim()).filter(Boolean) };
      if (editing) {
        await api("/api/admin/questions", "PATCH", { action: "edit", id: editing.id, version: editing.version, question });
        setNotice(editing.status === "published" ? "Yeni qaralama versiya saxlanıldı. Mövcud nəşr aktivdir." : "Qaralama yeniləndi.");
      } else {
        await api("/api/admin/questions", "POST", { question });
        setNotice("Sual qaralama kimi bazaya əlavə edildi. Yoxlayıb nəşr edin.");
      }
      setEditing(null);
      setTagText("");
      setEditor({ ...emptyEditor, topic: editor.topic, level: editor.level, complexity: editor.complexity, sourceTitle: editor.sourceTitle, sourceUrl: editor.sourceUrl });
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Sual saxlanmadı."); }
    finally { setBusy(false); }
  }

  async function changeStatus(row: Row, action: "publish" | "retire") {
    setBusy(true); setError(""); setNotice("");
    try {
      await api("/api/admin/questions", "PATCH", { action, id: row.id, version: row.version });
      setNotice(action === "publish" ? "Sual nəşr olundu. Yeni istifadəçi testlərində görünə bilər." : "Sual dövriyyədən çıxarıldı.");
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Status dəyişmədi."); }
    finally { setBusy(false); }
  }

  async function generate(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const data = await api<{ reply: string; questions: Row[] }>("/api/admin/questions/generate", "POST", {
        topic: editor.topic, level: editor.level, complexity: editor.complexity,
        sourceTitle: editor.sourceTitle, sourceUrl: editor.sourceUrl,
        prompt, count, history: messages.slice(-8),
      });
      setMessages((current) => [...current, { role: "admin" as const, text: prompt }, {
        role: "assistant" as const, text: `${data.reply}\n\n${data.questions.map((row) => `• ${row.question.prompt}`).join("\n")}`,
      }].slice(-8));
      setPrompt("");
      setFilter("draft");
      setNotice(`${data.questions.length} AI sualı bazada qaralama kimi saxlanıldı. Cavabları və mənbəni yoxlayıb nəşr edin.`);
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "AI sual hazırlaya bilmədi."); }
    finally { setBusy(false); }
  }

  const filtered = rows.filter((row) => filter === "all" || row.status === filter);
  const counts = {
    all: rows.length,
    draft: rows.filter((row) => row.status === "draft").length,
    published: rows.filter((row) => row.status === "published").length,
    retired: rows.filter((row) => row.status === "retired").length,
  };

  return <div className="admin-shell">
    <header className="admin-header"><div className="admin-header-inner"><Brand /><nav aria-label="Admin naviqasiyası"><Link href="/java">İstifadəçi görünüşü</Link><span>Sual bankı</span></nav><div className="admin-identity"><span>{name}</span><button type="button" onClick={async () => { try { await api("/api/admin/session", "DELETE"); router.replace("/admin/login"); router.refresh(); } catch { setError("Çıxış mümkün olmadı. Yenidən cəhd edin."); } }}>Çıxış</button></div></div></header>
    <main className="admin-main">
      <div className="admin-heading"><div><span className="admin-kicker">İdarəetmə paneli</span><h1>Sual bankı</h1><p>Sualları yaradın, cavabları yoxlayın və hazır olduqda istifadəçilər üçün nəşr edin.</p></div><div className="admin-stat"><strong>{counts.published}</strong><span>Nəşr olunmuş admin sualı</span></div></div>
      {error && <div className="admin-alert admin-alert-error" role="alert">{error}</div>}
      {notice && <div className="admin-alert admin-alert-success" role="status">{notice}</div>}
      <div className="admin-grid">
        <section className="admin-panel admin-compose" aria-label="Sual yaratma">
          <div className="admin-tabs" role="tablist" aria-label="Yaratma üsulu">
            <button type="button" role="tab" aria-selected={tab === "manual"} className={tab === "manual" ? "active" : ""} onClick={() => setTab("manual")}>Əl ilə yaz</button>
            <button type="button" role="tab" aria-selected={tab === "ai"} className={tab === "ai" ? "active" : ""} onClick={() => setTab("ai")}>AI ilə hazırla</button>
          </div>
          <div className="admin-panel-body">
            <div className="admin-section-heading"><h2>{tab === "manual" ? editing ? "Sualı redaktə et" : "Yeni sual" : "AI köməkçisi"}</h2><p>{tab === "manual" ? "Nəşrdən əvvəl cavab açarını və mənbəni yoxlayın." : "İstiqaməti promptla verin. Nəticələr bazaya qaralama kimi yazılır."}</p></div>
            <form onSubmit={tab === "manual" ? save : generate}>
            <div className="admin-fields admin-fields-three">
              <label>Mövzu<select value={editor.topic} onChange={(event) => changeTopic(event.target.value)}>{topics.map((topic) => <option key={topic.id} value={topic.id}>{topic.title}</option>)}</select></label>
              <label>Səviyyə<select value={editor.level} onChange={(event) => changeLevel(event.target.value as Level)}>{levels.filter((level) => levels.indexOf(level) >= levels.indexOf(topics.find((topic) => topic.id === editor.topic)?.level ?? "Junior")).map((level) => <option key={level}>{level}</option>)}</select></label>
              <label>Çətinlik (0–{caps[editor.level]})<input type="number" min="0" max={caps[editor.level]} value={editor.complexity} onChange={(event) => change("complexity", Number(event.target.value))} /></label>
            </div>
            <div className="admin-fields admin-fields-two">
              <label>Mənbə adı<input required maxLength={300} value={editor.sourceTitle} onChange={(event) => change("sourceTitle", event.target.value)} placeholder="Məsələn, Oracle Java documentation" /></label>
              <label>Mənbə linki (HTTPS)<input required type="url" pattern="https://.*" maxLength={2048} value={editor.sourceUrl} onChange={(event) => change("sourceUrl", event.target.value)} placeholder="https://..." /></label>
            </div>
            {tab === "manual" ? <div className="admin-editor-form">
              <label>Sual mətni<textarea required rows={4} maxLength={2000} value={editor.prompt} onChange={(event) => change("prompt", event.target.value)} placeholder="Namizəd üçün aydın və konkret sual yazın" /></label>
              <fieldset className="admin-options"><legend>Cavab variantları <small>Doğru variantları işarələyin</small></legend>{editor.options.map((option, index) => {
                const id = "abcd"[index];
                return <div className="admin-option" key={id}><label className="admin-correct"><input type="checkbox" checked={editor.correct.includes(id)} onChange={(event) => change("correct", event.target.checked ? [...editor.correct, id].sort() : editor.correct.filter((item) => item !== id))} aria-label={`${labels[index]} düzgün cavabdır`} /><span>{labels[index]}</span></label><input required maxLength={1000} value={option} onChange={(event) => change("options", editor.options.map((item, i) => i === index ? event.target.value : item))} aria-label={`${labels[index]} cavab variantı`} placeholder={`Variant ${labels[index]}`} /></div>;
              })}</fieldset>
              <label>İzah<textarea required rows={3} maxLength={3000} value={editor.explanation} onChange={(event) => change("explanation", event.target.value)} placeholder="Düzgün cavabın niyə doğru olduğunu izah edin" /></label>
              <label>Etiketlər <small>Vergüllə ayırın, maksimum 5</small><input value={tagText} onChange={(event) => setTagText(event.target.value)} placeholder="oop, collections" /></label>
              <div className="admin-actions"><button className="admin-primary" disabled={busy} type="submit">{busy ? "Saxlanır…" : editing ? "Dəyişiklikləri saxla" : "Qaralama saxla"}</button>{editing && <button className="admin-secondary" type="button" onClick={() => { setEditing(null); setEditor(emptyEditor); setTagText(""); }}>Ləğv et</button>}</div>
              {editing?.status === "published" && <p className="admin-help">Redaktə yeni qaralama versiya yaradır. Cari nəşr yenisi nəşr edilənə qədər görünür.</p>}
            </div> : <div className="admin-ai-form">
              <div className="admin-chat" aria-live="polite">{messages.length ? messages.map((message, index) => <div key={index} className={`admin-message ${message.role}`}><span>{message.role === "admin" ? "Siz" : "AI"}</span><p>{message.text}</p></div>) : <div className="admin-chat-empty"><strong>Prompt yazaraq başlayın</strong><p>Mövzu, sual növü və hansı bacarığı ölçmək istədiyinizi qeyd edin.</p></div>}</div>
              <label>AI üçün prompt<textarea required rows={4} maxLength={3000} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Məsələn: Java Map və equals/hashCode haqqında praktik, tək düzgün cavablı suallar hazırla..." /></label>
              <div className="admin-ai-submit"><label>Sual sayı<select value={count} onChange={(event) => setCount(Number(event.target.value))}><option value={1}>1</option><option value={2}>2</option><option value={3}>3</option></select></label><button className="admin-primary" disabled={busy} type="submit">{busy ? "Hazırlanır…" : "Sualları hazırla və saxla"}</button></div>
              <p className="admin-help">AI mənbə linkini avtomatik yoxlamır. Nəşrdən əvvəl sualı, cavab açarını və mənbəni yoxlayın.</p>
            </div>}
            </form>
          </div>
        </section>
        <section className="admin-panel admin-library" aria-label="Sual siyahısı"><div className="admin-library-head"><div><h2>Bazadakı suallar</h2><p>Admin tərəfindən yaradılan son 100 sual versiyası</p></div><button type="button" onClick={() => { setLoading(true); refresh().catch((cause) => setError(cause instanceof Error ? cause.message : "Siyahı yüklənmədi.")).finally(() => setLoading(false)); }} disabled={loading}>Yenilə</button></div>
          <div className="admin-filters" aria-label="Status filtri">{(["all", "draft", "published", "retired"] as const).map((item) => <button key={item} type="button" className={filter === item ? "active" : ""} aria-pressed={filter === item} onClick={() => setFilter(item)}>{({ all: "Hamısı", draft: "Qaralama", published: "Nəşrdə", retired: "Çıxarılmış" })[item]} <span>{counts[item]}</span></button>)}</div>
          <div className="admin-question-list">{loading ? <p className="admin-empty">Yüklənir…</p> : filtered.length ? filtered.map((row) => <article className="admin-question-card" key={`${row.id}:${row.version}`}><div className="admin-card-meta"><span className={`admin-badge ${row.status}`}>{({ draft: "Qaralama", published: "Nəşrdə", retired: "Çıxarılıb" })[row.status]}</span><span>{row.question.editorialOrigin === "ai" ? "AI" : "Manual"}</span><span>v{row.version}</span></div><h3>{row.question.prompt}</h3><p>{topics.find((topic) => topic.id === row.question.topic)?.title} · {row.question.level} · {row.question.complexity}/10</p><div className="admin-card-actions"><button type="button" onClick={() => selectRow(row)} disabled={busy || row.status === "retired"}>Bax / redaktə et</button>{row.status === "draft" && <button type="button" className="admin-publish" disabled={busy} onClick={() => changeStatus(row, "publish")}>Nəşr et</button>}{row.status === "published" && <button type="button" disabled={busy} onClick={() => changeStatus(row, "retire")}>Dövriyyədən çıxar</button>}</div></article>) : <p className="admin-empty">Bu statusda sual yoxdur.</p>}</div>
        </section>
      </div>
    </main>
  </div>;
}
