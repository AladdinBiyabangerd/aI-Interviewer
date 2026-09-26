"use client";

import { useEffect, useState } from "react";

type MeResponse = {
  authenticated?: boolean;
  display_name?: string;
  portal_url?: string;
  reason?: string;
};

export function PortalAccountChip({ language }: { language: "az" | "en" }) {
  const t = (az: string, en: string) => language === "az" ? az : en;
  const [me, setMe] = useState<MeResponse | null>(null);
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/auth/me", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const data = (await response.json()) as MeResponse;
        setMe(data);
        setAvailable(data.reason !== "not_configured");
      })
      .catch(() => {
        if (!controller.signal.aborted) setAvailable(false);
      });
    return () => controller.abort();
  }, []);

  if (!available) return null;

  const portalUrl = (me?.portal_url || "").trim();
  const displayName = (me?.display_name || "").trim();
  const initials = displayName
    ? displayName.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("")
    : "";

  if (me?.authenticated) {
    return <div className="qa-portal-account">
      {displayName ? <span className="qa-portal-name" title={displayName}>
        <span className="qa-portal-avatar" aria-hidden="true">{initials || "?"}</span>
        <span className="qa-portal-name-text">{displayName}</span>
      </span> : null}
      {portalUrl ? <a className="qa-portal-link" href={portalUrl}>{t("Portal", "Portal")}</a> : null}
      <form action="/api/auth/logout" method="post">
        <button className="qa-portal-logout" type="submit">{t("Çıxış", "Sign out")}</button>
      </form>
    </div>;
  }

  return <a className="qa-portal-btn" href="/api/auth/login">
    {t("Ingress ilə daxil ol", "Sign in with Ingress")}
  </a>;
}
