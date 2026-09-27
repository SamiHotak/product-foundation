import type { Metadata } from "next";

import { CompanyAddress, LegalPage, Value } from "@/components/marketing/legal-page";
import { legal } from "@/config/legal";

export const metadata: Metadata = { title: "Imprint" };

/** Impressum (Germany: § 5 DDG). Every business website needs one, reachable in two clicks. */
export default function ImprintPage() {
  const c = legal.company;
  return (
    <LegalPage title="Imprint" intro="Information according to § 5 DDG (Impressum).">
      <h2>Provider</h2>
      <CompanyAddress />
      {c.representedBy && (
        <p>
          Represented by: <Value>{c.representedBy}</Value>
        </p>
      )}

      <h2>Contact</h2>
      <p>
        Phone: <Value>{c.phone}</Value>
        <br />
        Email: <Value>{c.email}</Value>
      </p>

      {c.register && (
        <>
          <h2>Register entry</h2>
          <p>
            <Value>{c.register}</Value>
          </p>
        </>
      )}

      {c.vatId && (
        <>
          <h2>VAT ID</h2>
          <p>
            VAT identification number according to § 27a UStG: <Value>{c.vatId}</Value>
          </p>
        </>
      )}

      <h2>Consumer dispute resolution</h2>
      <p>
        We are neither willing nor obliged to take part in dispute resolution proceedings before a
        consumer arbitration board.
      </p>
    </LegalPage>
  );
}
