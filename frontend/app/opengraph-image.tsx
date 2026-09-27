import { ImageResponse } from "next/og";

import { marketing } from "@/config/marketing";
import { product } from "@/config/product";

/** The picture shown when someone shares a link (LinkedIn, Slack, WhatsApp, ...). */
export const alt = `${product.name}: ${product.tagline}`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        padding: 72,
        background: "#f1f3f6",
        color: "#1b2233",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
        <div
          style={{
            width: 64,
            height: 64,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: product.accent.light,
            color: product.accent.onLight ?? "#ffffff",
            borderRadius: 14,
            fontSize: 34,
            fontWeight: 700,
          }}
        >
          {product.monogram}
        </div>
        <div style={{ fontSize: 36, fontWeight: 700 }}>{product.name}</div>
      </div>
      <div style={{ fontSize: 68, fontWeight: 700, lineHeight: 1.05, letterSpacing: -2 }}>
        {marketing.hero.title}
      </div>
      <div style={{ display: "flex", height: 10, width: 220, background: product.accent.light }} />
    </div>,
    size,
  );
}
