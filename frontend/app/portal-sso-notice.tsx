"use client";

import { useEffect, useState } from "react";

type Language = "az" | "en";

export function PortalSsoNotice({ language }: { language: Language }) {
  const [errorCode, setErrorCode] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const url = new URL(window.location.href);
    const error = url.searchParams.get("sso_error");
    if (error) queueMicrotask(() => { if (active) setErrorCode(error); });
    if (error || url.searchParams.has("sso")) {
      url.searchParams.delete("sso_error");
      url.searchParams.delete("sso");
      const query = url.searchParams.toString();
      window.history.replaceState(null, "", `${url.pathname}${query ? `?${query}` : ""}${url.hash}`);
    }
    return () => { active = false; };
  }, []);

  if (!errorCode) return null;
  const denied = errorCode === "access_denied";
  const message = language === "az"
    ? denied
      ? "Portal girişi ləğv edildi. İstədiyiniz vaxt yenidən cəhd edə bilərsiniz."
      : "Portal girişi tamamlanmadı. Bir qədər sonra yenidən cəhd edin."
    : denied
      ? "Portal sign-in was cancelled. You can try again whenever you are ready."
      : "Portal sign-in could not be completed. Please try again shortly.";

  return <div className="qa-sso-notice" role="alert">
    <span>{message}</span>
    <button type="button" onClick={() => setErrorCode(null)} aria-label={language === "az" ? "Bildirişi bağla" : "Dismiss notification"}>×</button>
  </div>;
}
