"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

export default function LoginForm() {
  const router = useRouter();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const response = await fetch("/api/admin/session", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        const result = await response.json();
        setError(result.code === "invalid_credentials" ? "İstifadəçi adı və ya parol yanlışdır."
          : result.code === "rate_limited" ? "Çox sayda giriş cəhdi var. Bir az sonra yenidən yoxlayın."
            : "Giriş mümkün olmadı. Yenidən cəhd edin.");
        return;
      }
      router.replace("/admin");
      router.refresh();
    } catch { setError("Giriş mümkün olmadı. Yenidən cəhd edin."); }
    finally { setBusy(false); }
  }

  return <form className="admin-login-form" onSubmit={login}>
    <label>İstifadəçi adı<input required autoComplete="username" maxLength={120} value={username} onChange={(event) => setUsername(event.target.value)} /></label>
    <label>Parol<input required type="password" autoComplete="current-password" maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
    {error && <p className="admin-login-error" role="alert">{error}</p>}
    <button className="admin-primary" disabled={busy} type="submit">{busy ? "Yoxlanır…" : "Daxil ol"}</button>
  </form>;
}
