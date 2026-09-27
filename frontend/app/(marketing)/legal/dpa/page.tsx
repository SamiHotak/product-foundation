import type { Metadata } from "next";
import Link from "next/link";

import { CompanyAddress, LegalPage, Value } from "@/components/marketing/legal-page";
import { product } from "@/config/product";

export const metadata: Metadata = { title: "Data processing agreement" };

/**
 * AVV / DPA (Art. 28 GDPR) between us (processor) and business customers (controllers).
 * The technical measures listed are the ones this code base really has; keep them true.
 */
export default function DpaPage() {
  const name = product.name;
  return (
    <LegalPage
      title="Data processing agreement"
      intro={`Auftragsverarbeitungsvertrag (AVV) according to Art. 28 GDPR, for customers of ${name}.`}
    >
      <h2>1. Parties and subject</h2>
      <p>
        This agreement is part of the contract for {name} (see the Terms). The customer is the
        controller. The processor is:
      </p>
      <CompanyAddress />
      <p>
        We process personal data only to provide {name} to the customer, for as long as the main
        contract runs.
      </p>

      <h2>2. Data and people concerned</h2>
      <ul>
        <li>
          <strong>Data:</strong> names, email addresses, account and usage data, IP addresses in
          logs, and all content the customer stores in {name}.
        </li>
        <li>
          <strong>People:</strong> the customer&apos;s users (employees, invited team members) and
          people whose data the customer stores in {name}.
        </li>
      </ul>

      <h2>3. Instructions</h2>
      <p>
        We process the data only on the customer&apos;s documented instructions: this agreement, the
        main contract and the settings the customer uses in the app. We tell the customer if we
        think an instruction breaks data protection law.
      </p>

      <h2>4. Confidentiality</h2>
      <p>Everyone who can access the data is bound to confidentiality.</p>

      <h2>5. Security measures (Art. 32 GDPR)</h2>
      <ul>
        <li>Servers and backups in data centres in Germany</li>
        <li>Encrypted connections (TLS) for all traffic</li>
        <li>
          Passwords stored only as Argon2id hashes; API keys and sign-in tokens only as hashes
        </li>
        <li>Role-based access inside each workspace; every workspace&apos;s data is kept apart</li>
        <li>Brute-force protection and rate limits on sign-in and the API</li>
        <li>Audit log of security-relevant actions</li>
        {/* Phase 5 builds these two. Keep the brackets until they are really in place. */}
        <li>
          <Value>[Daily database backups, restore tested]</Value>
        </li>
        <li>
          <Value>
            [Access to production servers only for named people, with personal SSH keys]
          </Value>
        </li>
      </ul>

      <h2>6. Subprocessors</h2>
      <p>
        The customer agrees to the subprocessors listed in the{" "}
        <Link href="/legal/privacy">privacy policy</Link> (section 3). We tell the customer at least
        30 days before adding or replacing one; the customer may object for an important reason. We
        bind every subprocessor to the same data protection duties.
      </p>

      <h2>7. Support for the customer</h2>
      <p>
        We help the customer answer requests from data subjects (for example with the built-in
        export and delete functions), and with security, breach notifications and data protection
        impact assessments where needed.
      </p>

      <h2>8. Data breaches</h2>
      <p>
        We inform the customer without undue delay, and within <Value>[24]</Value> hours of becoming
        aware, about any breach affecting the customer&apos;s data.
      </p>

      <h2>9. End of the contract</h2>
      <p>
        After the contract ends, we delete the customer&apos;s data within 14 days, unless the law
        requires us to keep it. Before that, the customer can export all data in the app. Backups
        are overwritten within <Value>[14]</Value> days.
      </p>

      <h2>10. Audits</h2>
      <p>
        We give the customer the information needed to show compliance with this agreement, and
        allow audits after reasonable notice, during business hours and without disturbing
        operations.
      </p>
    </LegalPage>
  );
}
