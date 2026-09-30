/**
 * Who runs this website, for the legal pages (/legal/imprint, /privacy, /terms, /dpa).
 *
 * IMPORTANT: the texts are STARTING POINTS, not legal advice. Before you go live:
 * 1. Fill in every [bracketed] value below.
 * 2. Have the texts checked by a lawyer, or replace them with texts from a generator you pay
 *    for (e.g. eRecht24, IT-Recht Kanzlei, Händlerbund). See docs/LEGAL_TEMPLATES.md.
 * 3. Then set `reviewed: true`. Until then every legal page shows a warning box.
 */

export type Processor = {
  name: string;
  purpose: string;
  /** Where the data is processed. */
  location: string;
  /** Only for countries outside the EU/EEA, e.g. "EU-US Data Privacy Framework + SCCs". */
  transfer?: string;
};

export type LegalConfig = {
  reviewed: boolean;
  /** Date the current texts apply from (YYYY-MM-DD). */
  updated: string;
  company: {
    /** Full name of the person or company, incl. legal form (e.g. "Muster GmbH"). */
    name: string;
    /** For a GmbH/UG: the managing director(s). For a sole trader: leave empty. */
    representedBy: string;
    street: string;
    postalCode: string;
    city: string;
    country: string;
    email: string;
    /** Germany: a second fast way to reach you is required (phone is the usual one). */
    phone: string;
    /** "USt-IdNr." if you have one, else empty. */
    vatId: string;
    /** Commercial register, e.g. "Amtsgericht Mönchengladbach, HRB 12345". Empty if none. */
    register: string;
  };
  /** The data protection authority for your state (Germany: the Landesbeauftragte). */
  supervisoryAuthority: { name: string; url: string };
  /** Service providers that process personal data for you (Art. 28 GDPR). */
  processors: Processor[];
};

export const legal: LegalConfig = {
  reviewed: false,
  updated: "2026-09-30",
  company: {
    name: "[Your name or company name]",
    representedBy: "",
    street: "[Street and number]",
    postalCode: "[Postal code]",
    city: "[City]",
    country: "Germany",
    email: "[hello@your-domain.com]",
    phone: "[+49 ...]",
    vatId: "",
    register: "",
  },
  supervisoryAuthority: {
    name: "Landesbeauftragte für Datenschutz und Informationsfreiheit Nordrhein-Westfalen (LDI NRW)",
    url: "https://www.ldi.nrw.de",
  },
  processors: [
    {
      name: "Hetzner Online GmbH",
      purpose: "Servers, database, backups and file storage (Hetzner Object Storage)",
      location: "Germany",
    },
    {
      name: "OpenAI Ireland Ltd. (OpenAI)",
      purpose:
        "AI features: the text you send to an AI feature is processed to create the answer (API data is not used for training; OpenAI may keep it up to 30 days for abuse monitoring)",
      location: "[USA, or EU with OpenAI's EU data residency]",
      transfer: "[EU-US Data Privacy Framework and/or Standard Contractual Clauses]",
    },
    {
      name: "Langfuse GmbH",
      purpose:
        "Monitoring AI requests (costs, errors, quality); texts only if LLM_TRACE_CONTENT is on",
      location: "[EU (Frankfurt) with Langfuse Cloud EU, or our own server]",
    },
    {
      name: "[Resend or Postmark]",
      purpose: "Sending emails (sign-in links, invites, receipts)",
      location: "[EU or USA]",
      transfer: "[EU-US Data Privacy Framework and/or Standard Contractual Clauses]",
    },
    {
      name: "Stripe Payments Europe, Ltd.",
      purpose: "Payments and invoices",
      location: "Ireland (EU), with transfers to the USA",
      transfer: "EU-US Data Privacy Framework and Standard Contractual Clauses",
    },
    {
      name: "Functional Software, Inc. (Sentry)",
      purpose: "Error reports, so we can fix bugs",
      location: "[EU region or USA]",
      transfer: "[EU-US Data Privacy Framework and/or Standard Contractual Clauses]",
    },
    {
      name: "[Plausible Insights OÜ or Umami Software, Inc.]",
      purpose: "Cookie-less visitor statistics (no cookies, no profiles)",
      location: "[EU]",
    },
  ],
};

/** True while any value still has a [placeholder]. */
export function legalHasPlaceholders(config: LegalConfig = legal): boolean {
  return JSON.stringify(config).includes("[");
}
