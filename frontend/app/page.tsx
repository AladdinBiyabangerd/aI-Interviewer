"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Brand } from "./brand";
import "./assessment.css";

type Language = "az" | "en";

export default function HomePage() {
  const [language, setLanguage] = useState<Language>("az");
  const t = (az: string, en: string) => language === "az" ? az : en;

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      const saved = localStorage.getItem("intervia:language");
      if (saved === "az" || saved === "en") setLanguage(saved);
    });
    return () => { active = false; };
  }, []);
  useEffect(() => { document.documentElement.lang = language; }, [language]);

  return <div className="qa-app qa-landing">
    <a className="qa-skip-link" href="#qa-main">{t("Əsas məzmuna keç", "Skip to content")}</a>
    <header className="qa-header"><div>
      <Brand />
      <span className="qa-header-label">{t("Müsahibəyə hazırlıq", "Interview preparation")}</span>
      <div className="qa-header-actions">
        <a href="#tracks">{t("İstiqamətlər", "Tracks")}</a>
        <label className="qa-language">{t("Dil", "Language")}
          <select value={language} onChange={(event) => { const next = event.target.value as Language; localStorage.setItem("intervia:language", next); setLanguage(next); }}><option value="az">AZ</option><option value="en">EN</option></select>
        </label>
      </div>
    </div></header>

    <main id="qa-main" className="qa-main" tabIndex={-1}>
      <section className="qa-hero">
        <div>
          <p className="eyebrow">{t("Sənin inkişaf yolun", "Your path forward")}</p>
          <h1>{t("Növbəti müsahibəyə", "Walk into your next interview")}<br /><em>{t("hazır gir.", "ready.")}</em></h1>
          <p className="qa-lead">{t("İstiqamətini seç, sualları öz tempində cavablandır və nəticələrini sonda nəzərdən keçir. AI Interviewer müxtəlif sahələr üzrə müsahibə hazırlığı üçün qurulur.", "Choose a track, answer at your own pace, and review your results at the end. AI Interviewer is growing into an interview preparation space for different fields.")}</p>
          <a className="button button-primary qa-hero-cta" href="#tracks">{t("İstiqamət seç", "Choose a track")} <span aria-hidden="true">→</span></a>
          <div className="qa-hero-pills"><span>{t("Öz tempində məşq", "Practice at your pace")}</span><span>{t("Cavablar sonda", "Answers at the end")}</span><span>{t("Sessiya saxlanır", "Progress is saved")}</span></div>
        </div>
        <aside className="qa-preview" aria-label={t("AI Interviewer haqqında", "About AI Interviewer")}>
          <div className="qa-preview-top"><span>AI INTERVIEWER</span><span>{t("HAZIRLIQ", "PRACTICE")}</span></div>
          <p>{t("Hazırlıq bir seçimlə başlayır.", "Preparation starts with a choice.")}</p>
          <div className="qa-preview-option"><span aria-hidden="true">✓</span>{t("İstiqamətini seç, məşq et və nəyi inkişaf etdirməli olduğunu gör.", "Choose your track, practice, and see where to improve.")}</div>
          <p className="qa-preview-note">{t("İlk açıq istiqamət Java-dır. Yeni sahələr hazır olduqca burada yer alacaq.", "Java is the first available track. More fields will appear here as they become ready.")}</p>
        </aside>
      </section>

      <section id="tracks" className="qa-track-section" aria-labelledby="qa-tracks-title">
        <div className="qa-section-heading"><div><p className="eyebrow">{t("İstiqamətlər", "Tracks")}</p><h2 id="qa-tracks-title">{t("Nə üzrə hazırlaşmaq istəyirsən?", "What are you preparing for?")}</h2></div><p>{t("İndi açıq olan istiqaməti seç", "Choose an available track")}</p></div>
        <div className="qa-track-grid">
          <article className="qa-track-card qa-track-card-active">
            <div className="qa-track-top"><span className="qa-track-icon" aria-hidden="true">{`{ }`}</span><span className="qa-track-status">{t("Açıqdır", "Available")}</span></div>
            <h3>Java</h3>
            <p>{t("Java və backend biliklərini yoxla. Səviyyənə uyğun test seç və ya Java 8 kitabı üzrə məşq et.", "Check your Java and backend knowledge. Choose a level-based assessment or practice with the Java 8 book.")}</p>
            <div className="qa-track-tags"><span>Java & AI</span><span>Java 8</span><span>{t("Test uzunluğunu özün seç", "Choose your test length")}</span></div>
            <Link className="button button-primary qa-track-link" href="/java">{t("Java istiqamətinə keç", "Explore Java track")} <span aria-hidden="true">→</span></Link>
          </article>
          <article className="qa-track-card qa-track-card-upcoming">
            <div className="qa-track-top"><span className="qa-track-icon" aria-hidden="true">＋</span><span className="qa-track-status">{t("Tezliklə", "Coming soon")}</span></div>
            <h3>{t("Yeni sahələr", "More fields")}</h3>
            <p>{t("AI Interviewer başqa peşə və ixtisaslar üçün də müsahibə istiqamətləri əlavə edəcək. Hazır olduqda burada seçim kimi görünəcəklər.", "AI Interviewer will add interview tracks for other professions and specialties. They will appear here when they are ready.")}</p>
            <p className="qa-track-upcoming-note">{t("Hazırda sual bankı yalnız Java istiqaməti üçün açıqdır.", "The question bank is currently available for Java only.")}</p>
          </article>
        </div>
      </section>
    </main>
    <footer className="qa-footer"><span>AI Interviewer · {t("Öyrənməyə davam et.", "Keep learning.")}</span><span>{t("Müsahibəyə hazırlıq", "Interview preparation")}</span></footer>
  </div>;
}
