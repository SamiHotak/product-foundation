import "@fontsource-variable/hanken-grotesk";
import "./globals.css";

import type { Metadata, Viewport } from "next";

import { ThemeProvider } from "@/components/theme-provider";
import { product } from "@/config/product";

export const metadata: Metadata = {
  title: { default: product.name, template: `%s · ${product.name}` },
  description: product.tagline,
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f1f3f6" },
    { media: "(prefers-color-scheme: dark)", color: "#0d1220" },
  ],
};

// The product accent from config/product.ts becomes a CSS variable used by every component.
const brandCss = `:root{--brand:${product.accent.light};--brand-dark:${product.accent.dark};}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: next-themes sets the class on <html> before React loads.
    <html lang="en" suppressHydrationWarning>
      <head>
        <style>{brandCss}</style>
      </head>
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
