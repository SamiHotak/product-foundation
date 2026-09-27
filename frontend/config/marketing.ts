/**
 * Website copy: the landing page, pricing page and FAQ. Each product rewrites this file
 * (together with config/product.ts for name, logo and colors, and config/legal.ts).
 *
 * Plans and prices are NOT here: they come from the backend (backend/app/core/plans.py),
 * so the website always shows what the app really sells and enforces.
 */
import type { LucideIcon } from "lucide-react";
import { Activity, Download, KeyRound, Moon, ScrollText, UsersRound } from "lucide-react";

export type Link = { label: string; href: string };

export type DemoVideo = {
  /** A file in public/ (e.g. "/demo.mp4") or a full https URL. MP4 (H.264) works everywhere. */
  src: string;
  /** Still image shown before play (put it in public/). Same aspect ratio as the video. */
  poster: string;
  /** Video size in pixels, so the page doesn't jump while loading. */
  width: number;
  height: number;
  /** Optional captions file (.vtt) for people who can't hear the video. */
  captions?: string;
};

export type MarketingConfig = {
  /** Links in the top bar (sections of the landing page or other pages). */
  nav: Link[];
  hero: {
    title: string;
    subtitle: string;
    primary: Link;
    secondary: Link;
    /**
     * The demo video in the hero. null = a built-in preview of the app is shown instead.
     * Self-host the file (public/ or your object storage). No YouTube/Vimeo embeds: they set
     * cookies before anyone clicks, which needs a consent banner in the EU.
     */
    video: DemoVideo | null;
  };
  features: {
    title: string;
    intro: string;
    items: { icon: LucideIcon; title: string; text: string }[];
  };
  steps: { title: string; items: { title: string; text: string }[] };
  pricing: { title: string; intro: string };
  faq: { title: string; items: { question: string; answer: string }[] };
  cta: { title: string; text: string; action: Link };
};

export const marketing: MarketingConfig = {
  nav: [
    { label: "Features", href: "/#features" },
    { label: "How it works", href: "/#how-it-works" },
    { label: "Pricing", href: "/pricing" },
    { label: "FAQ", href: "/#faq" },
  ],
  hero: {
    title: "Accounts, teams and background jobs, ready on day one",
    subtitle:
      "Sign-in, workspaces with roles, API keys, an audit log and data export are already built and tested. You start with the part your customers pay for.",
    primary: { label: "Create a free account", href: "/signup" },
    secondary: { label: "See pricing", href: "/pricing" },
    video: null,
  },
  features: {
    title: "What is already done",
    intro: "The parts every serious product needs, built once and tested end to end.",
    items: [
      {
        icon: UsersRound,
        title: "Workspaces and roles",
        text: "Invite people by email. Owners, admins and members each see only what they may use.",
      },
      {
        icon: Activity,
        title: "Live background jobs",
        text: "Long tasks run in the background. People watch the progress and get a clear message if something fails.",
      },
      {
        icon: KeyRound,
        title: "API keys",
        text: "Connect scripts and other tools with keys that have limited rights and can be revoked at any time.",
      },
      {
        icon: ScrollText,
        title: "Audit log",
        text: "See who changed what and when: sign-ins, role changes, exports and deletions.",
      },
      {
        icon: Download,
        title: "Your data stays yours",
        text: "Export everything as a ZIP file. Delete your account or workspace, with 14 days to change your mind.",
      },
      {
        icon: Moon,
        title: "Light and dark",
        text: "Follows your device, or pick one. Works the same on a phone and on a large screen.",
      },
    ],
  },
  steps: {
    title: "How it works",
    items: [
      {
        title: "Create your account",
        text: "Sign up with your email or Google. Your first workspace is ready right away.",
      },
      {
        title: "Invite your team",
        text: "Add people and choose what each of them may do.",
      },
      {
        title: "Get the work done",
        text: "Start tasks, follow them live, and connect your own tools with an API key.",
      },
    ],
  },
  pricing: {
    title: "Simple pricing",
    intro: "Start free. Upgrade when your team grows. Cancel at any time.",
  },
  faq: {
    title: "Questions and answers",
    items: [
      {
        question: "Is there a free plan?",
        answer:
          "Yes. The free plan has no time limit. Paid plans start with a free trial, and you can cancel before it ends.",
      },
      {
        question: "Where is my data stored?",
        answer:
          "On servers in Germany. We don't sell your data, and we only use service providers that follow the GDPR.",
      },
      {
        question: "Can I get my data out?",
        answer:
          "Yes. Settings → Privacy creates a ZIP file with all your data. Workspace owners and admins can export the whole workspace.",
      },
      {
        question: "Can I work with my team?",
        answer: "Yes. Invite people by email and give each of them a role: member, admin or owner.",
      },
      {
        question: "How do I cancel?",
        answer:
          "At any time, in Settings → Billing. You keep your plan until the end of the period you paid for.",
      },
      {
        question: "Do you offer a data processing agreement (AVV)?",
        answer:
          "Yes. Our data processing agreement is on the legal page and applies to all business customers.",
      },
    ],
  },
  cta: {
    title: "Try it with your own team",
    text: "Free to start. No credit card needed.",
    action: { label: "Create a free account", href: "/signup" },
  },
};
