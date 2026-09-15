import { ImageResponse } from "next/og";

export const alt = "AI Interviewer — müsahibəyə hazır gir";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", padding: "68px 76px", background: "#f7f8f4", color: "#172c29" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 30, fontWeight: 700 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 58, height: 58, borderRadius: 16, background: "#116b5b", color: "white", fontSize: 37 }}>I</div>
        AI Interviewer
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        <div style={{ display: "flex", color: "#116b5b", fontSize: 21, fontWeight: 700, letterSpacing: 2 }}>MÜSAHİBƏYƏ HAZIRLIQ</div>
        <div style={{ display: "flex", maxWidth: 900, fontSize: 70, fontWeight: 700, lineHeight: 1.1, letterSpacing: -3 }}>Növbəti müsahibəyə hazır gir.</div>
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: 23, borderTop: "2px solid #dce6df", color: "#52645e", fontSize: 20 }}>
        <span>İstiqamət seç · Öz tempində məşq et · Nəticəni gör</span>
        <span>AI Interviewer</span>
      </div>
    </div>,
    size,
  );
}
