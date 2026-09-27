/**
 * Product identity and theming. This is the ONE file each product (AskDocs, LeadPilot,
 * InvoiceAI Pro, CountVision) changes to look like itself:
 * name, logo, accent color, fonts, sidebar items and the "Get started" steps.
 *
 * Also change, to match:
 * - APP_NAME in deploy/docker-compose.dev.yml (the name in emails),
 * - public/ (put your logo files there, see `logo` below).
 */

// 1. FONT FILES. Install another font with `npm install @fontsource-variable/<font>` and
//    import it here instead, then put its name in `fonts` below. Self-hosted: no Google
//    requests, no cookie banner needed, and no layout shift.
import "@fontsource-variable/hanken-grotesk";

import type { LucideIcon } from "lucide-react";
import { LayoutDashboard, Settings } from "lucide-react";

import type { Permission } from "@/lib/api";

export type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Only shown to people who have this permission (backend/app/core/permissions.py). */
  needs?: Permission;
  /** Extra words that find this page in the command palette (Ctrl+K). */
  keywords?: string[];
};

/** Step keys the backend knows (backend/app/services/onboarding.py). */
export type OnboardingKey = "verify_email" | "invite_teammate" | "create_api_key" | "run_job";

export type OnboardingItem = {
  key: OnboardingKey;
  title: string;
  description: string;
  /** Where the step is done. */
  href: string;
  /** Button text, e.g. "Invite someone". */
  action: string;
};

export type ProductConfig = {
  /** Shown in the sidebar, browser tab and page titles. */
  name: string;
  /** One sentence: what the product does for the user. */
  tagline: string;
  /** Up to 2 letters for the square logo mark (used when there is no logo, and as tab icon). */
  monogram: string;
  /**
   * Optional logo image from public/ (SVG or PNG), shown instead of the monogram square.
   * `darkSrc` is used in dark mode (e.g. a white version). `wordmark: true` means the image
   * already contains the name, so the name text is hidden next to it.
   */
  logo: { src: string; darkSrc?: string; width: number; height: number; wordmark?: boolean } | null;
  /**
   * Accent color for light and dark mode (hex). Buttons, links, the active menu item.
   * `onAccent` is the text color on accent buttons; check contrast >= 4.5:1
   * (https://webaim.org/resources/contrastchecker/).
   */
  accent: { light: string; dark: string; onLight?: string; onDark?: string };
  /** CSS font-family names. Must match the fonts imported at the top of this file. */
  fonts: { sans: string; heading?: string };
  /** Main navigation in the sidebar, top to bottom. */
  nav: NavItem[];
  /** Pinned to the bottom of the sidebar. */
  navFooter: NavItem[];
  /** The "Get started" checklist on the dashboard, in this order. */
  onboarding: OnboardingItem[];
};

export const product: ProductConfig = {
  name: "Foundation",
  tagline: "The shared base for every product.",
  monogram: "F",
  logo: null,
  accent: { light: "#244BA6", dark: "#86A4F4" },
  fonts: { sans: "Hanken Grotesk Variable" },
  nav: [{ label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, keywords: ["home"] }],
  navFooter: [
    {
      label: "Settings",
      href: "/settings",
      icon: Settings,
      keywords: ["profile", "account", "preferences"],
    },
  ],
  onboarding: [
    {
      key: "verify_email",
      title: "Confirm your email",
      description: "So we can reach you about your account.",
      href: "/settings",
      action: "Open profile",
    },
    {
      key: "invite_teammate",
      title: "Invite a teammate",
      description: "Work together in this workspace. You choose what they may do.",
      href: "/settings/members",
      action: "Invite someone",
    },
    {
      key: "create_api_key",
      title: "Create an API key",
      description: "Connect your own scripts and tools to this workspace.",
      href: "/settings/api-keys",
      action: "Create a key",
    },
    {
      key: "run_job",
      title: "Run a background job",
      description: "See how long tasks run in the background with live progress.",
      href: "/dashboard#jobs",
      action: "Try it",
    },
  ],
};

/** CSS variables for <html style>, from the config above (see app/layout.tsx). */
export function brandStyle(config: ProductConfig = product): Record<string, string> {
  const vars: Record<string, string> = {
    "--brand": config.accent.light,
    "--brand-dark": config.accent.dark,
    "--brand-font": `"${config.fonts.sans}"`,
    "--brand-font-heading": `"${config.fonts.heading ?? config.fonts.sans}"`,
  };
  if (config.accent.onLight) vars["--brand-ink"] = config.accent.onLight;
  if (config.accent.onDark) vars["--brand-ink-dark"] = config.accent.onDark;
  return vars;
}
