/**
 * Product identity. This is the ONE file each product (AskDocs, LeadPilot,
 * InvoiceAI Pro, CountVision) changes to look like itself.
 * Phase 3 extends it (logo image, fonts, marketing copy).
 */
import type { LucideIcon } from "lucide-react";
import { LayoutDashboard, Settings } from "lucide-react";

export type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
};

export type ProductConfig = {
  /** Shown in the sidebar, browser tab and emails. */
  name: string;
  /** One sentence: what the product does for the user. */
  tagline: string;
  /** Up to 2 letters for the square logo mark. */
  monogram: string;
  /** Accent color for light and dark mode (hex). Keep good contrast with white / dark text. */
  accent: { light: string; dark: string };
  /** Main navigation in the sidebar, top to bottom. */
  nav: NavItem[];
};

export const product: ProductConfig = {
  name: "Foundation",
  tagline: "The shared base for every product.",
  monogram: "F",
  accent: { light: "#244BA6", dark: "#86A4F4" },
  nav: [
    { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    { label: "Settings", href: "/settings", icon: Settings },
  ],
};
