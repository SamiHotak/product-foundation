import "./globals.css";

import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";

import { Analytics } from "@/components/analytics";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/toast";
import { brandStyle, product } from "@/config/product";
import { siteUrl } from "@/lib/site";
import { parseTheme, THEME_COOKIE, themeClass } from "@/lib/theme";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: { default: `${product.name}: ${product.tagline}`, template: `%s · ${product.name}` },
  description: product.tagline,
  openGraph: { type: "website", siteName: product.name },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f1f3f6" },
    { media: "(prefers-color-scheme: dark)", color: "#0d1220" },
  ],
};

// Accent color and fonts from config/product.ts become CSS variables used by every component.
// Set as a style on <html>, not a <style> tag in <head>: browser extensions often inject
// their own tags into <head>, and React would report a mismatch with ours.
const brandVars = brandStyle() as React.CSSProperties;

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Saved theme choice. Reading a cookie renders pages per request (needed so dark mode
  // is correct on the very first paint, without any script).
  const theme = parseTheme((await cookies()).get(THEME_COOKIE)?.value);
  return (
    // suppressHydrationWarning: <html> and <body> are often changed by browser extensions.
    <html lang="en" className={themeClass(theme)} style={brandVars} suppressHydrationWarning>
      <body suppressHydrationWarning>
        <ThemeProvider initialTheme={theme}>
          {children}
          <Toaster />
          <Analytics />
        </ThemeProvider>
      </body>
    </html>
  );
}
