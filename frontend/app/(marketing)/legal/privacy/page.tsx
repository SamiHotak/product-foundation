import type { Metadata } from "next";
import Link from "next/link";

import { CompanyAddress, LegalPage, Value } from "@/components/marketing/legal-page";
import { legal } from "@/config/legal";
import { product } from "@/config/product";

export const metadata: Metadata = { title: "Privacy policy" };

/**
 * Datenschutzerklärung (GDPR Art. 13). Describes what THIS code base really does; when a
 * product adds features (AI, file uploads, more providers), add them here too.
 */
export default function PrivacyPage() {
  const { company, processors, supervisoryAuthority } = legal;
  return (
    <LegalPage
      title="Privacy policy"
      intro={`How ${product.name} handles personal data, and the rights you have.`}
    >
      <h2>1. Who is responsible</h2>
      <p>The controller under the GDPR is:</p>
      <CompanyAddress />
      <p>
        Email: <Value>{company.email}</Value>
      </p>

      <h2>2. What we process, and why</h2>
      <h3>Visiting the website</h3>
      <p>
        Our server records each request (IP address, date and time, page, browser) to keep the
        service secure and find errors. Legal basis: our legitimate interest in a secure service
        (Art. 6 (1) (f) GDPR). These logs are deleted after <Value>[14]</Value> days.
      </p>

      <h3>Your account</h3>
      <p>
        When you create an account we process your name, email address and a password hash (never
        the password itself), plus what you create in your workspaces. We need this to provide the
        service (Art. 6 (1) (b) GDPR). If you sign in with Google, Google sends us your name, email
        address and a user ID.
      </p>

      <h3>Security and audit log</h3>
      <p>
        We record security events such as sign-ins, role changes, exports and deletions, with IP
        address and browser, to protect your account and your workspace (Art. 6 (1) (f) GDPR). These
        entries are deleted after 365 days.
      </p>

      <h3>Cookies</h3>
      <p>
        We only use cookies that are needed for the service. They need no consent (§ 25 (2) TDDDG):
      </p>
      <ul>
        <li>
          <code>session</code>: keeps you signed in. Up to 30 days.
        </li>
        <li>
          <code>session_admin</code>: only for our support staff while they view the app as a
          customer (keeps their own sign-in). At most 1 hour.
        </li>
        <li>
          <code>theme</code>: remembers light or dark mode, if you pick one. 1 year.
        </li>
        <li>
          <code>google_oauth</code>, <code>google_next</code>: protect the Google sign-in and
          remember which page to open afterwards. 10 minutes.
        </li>
      </ul>
      <p>We use no advertising or tracking cookies.</p>

      <h3>Visitor statistics</h3>
      <p>
        To see which pages are used, our server sends the page address (without any parameters), the
        website you came from (domain only) and your browser type to our statistics service. No
        cookies are set and nothing is stored on your device. Your IP address is used only to create
        a daily-changing, anonymous visitor count and is not stored. Legal basis: our legitimate
        interest in improving the website (Art. 6 (1) (f) GDPR). If your browser sends a &quot;Do
        Not Track&quot; or &quot;Global Privacy Control&quot; signal, we send nothing.
      </p>

      <h3>Emails</h3>
      <p>
        We send emails that belong to the service: confirming your address, password resets,
        invitations and receipts (Art. 6 (1) (b) GDPR).
      </p>

      <h3>Payments</h3>
      <p>
        Paid plans are handled by Stripe. You enter your card, billing address and VAT ID on
        Stripe&apos;s pages; we never see or store your card details. We store the Stripe customer
        number of your workspace, the plan, its status and renewal date, and how much of the plan
        limits the workspace used this month (Art. 6 (1) (b) GDPR). The workspace owner&apos;s name
        and email are sent to Stripe for invoices. Invoices are kept as long as tax and commercial
        law require (currently up to 10 years; Art. 6 (1) (c) GDPR).
      </p>

      <h3>Files</h3>
      <p>
        Files you upload are stored for your workspace in object storage in Germany (Hetzner), sent
        over encrypted connections only. We store the file, its name, size and type, who uploaded it
        and when. Everyone in the workspace can see and download them. Files are checked when they
        arrive (that they really are the type their name says<Value>[, and for viruses]</Value>).
        They are deleted when someone deletes them, or with the workspace (Art. 6 (1) (b) GDPR).
      </p>

      <h3>AI features</h3>
      <p>
        When you use an AI feature, the text you give it is sent to OpenAI to create the answer. We
        send it with the instruction not to store it (OpenAI may keep API data for up to 30 days to
        detect abuse) and OpenAI does not use API data to train its models. We store for each
        request: the workspace, who asked, the model, the number of tokens, the cost and whether it
        worked, so we can apply plan limits and bill correctly (Art. 6 (1) (b) GDPR). To find errors
        and improve quality, we record AI requests in Langfuse
        <Value>[including the text and the answer | without the text and the answer]</Value>; these
        records are deleted after <Value>[30]</Value> days (Art. 6 (1) (f) GDPR). Don&apos;t put
        special categories of personal data (e.g. health data) into AI features.
      </p>

      <h3>Support access</h3>
      <p>
        To help you, our support staff can view the app as you for a limited time (at most one
        hour). They can look, but not change your settings, team, password, billing or API keys, and
        not export your data. Every such view is recorded in the audit log of your workspace, so you
        can see it (Art. 6 (1) (b) and (f) GDPR).
      </p>

      <h3>Demo</h3>
      <p>
        The &quot;Try the demo&quot; button opens a shared workspace with invented sample data. It
        sets only the <code>session</code> cookie and is reset every night.
      </p>

      <h2>3. Service providers</h2>
      <p>These companies process data for us under a data processing agreement (Art. 28 GDPR):</p>
      <div className="overflow-x-auto">
        <table>
          <thead>
            <tr>
              <th scope="col">Provider</th>
              <th scope="col">Purpose</th>
              <th scope="col">Location</th>
            </tr>
          </thead>
          <tbody>
            {processors.map((p) => (
              <tr key={p.name}>
                <td>
                  <Value>{p.name}</Value>
                </td>
                <td>{p.purpose}</td>
                <td>
                  <Value>{p.location}</Value>
                  {p.transfer && (
                    <>
                      <br />
                      <span className="text-ink-muted">
                        Safeguard: <Value>{p.transfer}</Value>
                      </span>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>4. How long we keep data</h2>
      <p>
        We keep account and workspace data while your account exists. When you delete your account
        or a workspace, it is removed after 14 days (you can cancel during that time). Data exports
        are deleted after 7 days. Where the law requires us to keep something longer (for example
        invoices), we keep only that, and only as long as required.
      </p>

      <h2>5. Your rights</h2>
      <p>You have the right to:</p>
      <ul>
        <li>get a copy of your data (Art. 15 GDPR), also as a file (Art. 20 GDPR)</li>
        <li>have wrong data corrected (Art. 16 GDPR)</li>
        <li>have your data deleted (Art. 17 GDPR) or its use restricted (Art. 18 GDPR)</li>
        <li>object to processing based on our legitimate interest (Art. 21 GDPR)</li>
        <li>complain to a data protection authority (Art. 77 GDPR)</li>
      </ul>
      <p>
        You can export and delete your data yourself under{" "}
        <Link href="/settings/privacy">Settings → Privacy</Link>, or write to us. The authority
        responsible for us is the{" "}
        <a href={supervisoryAuthority.url} rel="noopener noreferrer">
          {supervisoryAuthority.name}
        </a>
        .
      </p>

      <h2>6. Do you have to give us your data?</h2>
      <p>
        You need to give your name, email address and a password (or use Google) to create an
        account. Without them we cannot provide the service. We make no automated decisions about
        you that have legal effects (Art. 22 GDPR).
      </p>

      <h2>7. Changes</h2>
      <p>
        We update this policy when the service changes. The date at the top shows the current
        version.
      </p>
    </LegalPage>
  );
}
