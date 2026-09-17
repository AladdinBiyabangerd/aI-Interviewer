"use client";

import { useEffect, useState } from "react";

type MeResponse = {
  authenticated?: boolean;
  display_name?: string;
  given_name?: string;
  family_name?: string;
  portal_url?: string;
  reason?: string;
};

type Props = {
  language: "az" | "en";
};

export function PortalAccountChip({ language }: Props) {
  const t = (az: string, en: string) => (language === "az" ? az : en);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    let active = true;
    fetch("/api/auth/me", { cache: "no-store" })
      .then(async (response) => {
        const data = (await response.json()) as MeResponse;
        if (!active) return;
        setMe(data);
        setAvailable(data.reason !== "not_configured");
      })
      .catch(() => {
        if (active) setAvailable(false);
      });
    return () => {
      active = false;
    };
  }, []);

  if (!available) return null;

  const portalUrl = (me?.portal_url || "").trim();
  const displayName = (me?.display_name || "").trim();
  const initials = displayName
    ? displayName.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase() ?? "").join("")
    : "";

  if (me?.authenticated) {
    return (
      <div className="qa-portal-account">
        {displayName ? (
          <span className="qa-portal-name" title={displayName}>
            <span className="qa-portal-avatar" aria-hidden="true">{initials || "?"}</span>
            <span className="qa-portal-name-text">{displayName}</span>
          </span>
        ) : null}
        {portalUrl ? (
          <a className="qa-portal-btn" href={portalUrl}>
            {t("Portal", "Portal")}
          </a>
        ) : null}
        <a className="qa-portal-logout" href="/api/auth/logout">
          {t("Çıxış", "Sign out")}
        </a>
      </div>
    );
  }

  return (
    <a className="qa-portal-btn" href="/api/auth/login">
      {t("Portal", "Portal")}
    </a>
  );
}
