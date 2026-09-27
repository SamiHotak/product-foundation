import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage, Value } from "@/components/marketing/legal-page";
import { legal } from "@/config/legal";
import { product } from "@/config/product";

export const metadata: Metadata = { title: "Terms" };

/**
 * AGB (terms of service). Written for BUSINESS customers only (§ 14 BGB). Selling to
 * consumers needs more: a withdrawal policy (Widerrufsbelehrung), the "cancel contract" button
 * (§ 312k BGB) and consumer rules on price display. See docs/LEGAL_TEMPLATES.md.
 */
export default function TermsPage() {
  const c = legal.company;
  const name = product.name;
  return (
    <LegalPage title="Terms" intro={`Terms of service for ${name}, for business customers.`}>
      <h2>1. Scope</h2>
      <p>
        These terms apply to all contracts between <Value>{c.name}</Value> (&quot;we&quot;) and our
        customers (&quot;you&quot;) about the use of {name}. {name} is offered only to businesses
        within the meaning of § 14 BGB, not to consumers. Your own terms do not apply, even if we
        don&apos;t object to them.
      </p>

      <h2>2. Contract</h2>
      <p>
        The contract starts when you create an account. A paid plan starts when you complete the
        checkout. The functions of each plan are described on the{" "}
        <Link href="/pricing">pricing page</Link> at the time you book it.
      </p>

      <h2>3. Our service</h2>
      <p>
        We provide {name} as software over the internet. We aim for an availability of{" "}
        <Value>[99.5]</Value>% per month, not counting announced maintenance and problems outside
        our control. We may improve and change functions as long as the main purpose of your plan
        stays the same.
      </p>

      <h2>4. Free plan and trial</h2>
      <p>
        The free plan and trials are free of charge and can be changed or ended by us with 30
        days&apos; notice. A trial ends automatically unless you choose a paid plan.
      </p>

      <h2>5. Prices and payment</h2>
      <p>
        Prices are shown on the pricing page, plus VAT. Fees are paid in advance for the chosen
        period (monthly or yearly) through our payment provider. If a payment fails, we may restrict
        access after a reminder.
      </p>

      <h2>6. Term and cancellation</h2>
      <p>
        Paid plans renew automatically for the same period. You can cancel at any time in the app,
        effective at the end of the current period. We can cancel with 30 days&apos; notice to the
        end of a period. The right to cancel for good cause is not affected.
      </p>

      <h2>7. Your duties</h2>
      <ul>
        <li>keep your passwords and API keys secret, and tell us if they may be known to others</li>
        <li>
          use {name} only in line with the law; no spam, malware or content you have no rights to
        </li>
        <li>don&apos;t try to get around limits or security measures, or overload the service</li>
      </ul>
      <p>We may block access if there is clear evidence of a serious breach of these duties.</p>

      <h2>8. Your data</h2>
      <p>
        Your data stays yours. We process personal data on your behalf according to our{" "}
        <Link href="/legal/dpa">data processing agreement</Link>, which is part of this contract.
        You can export your data at any time. After the contract ends we delete it within the
        periods stated in the <Link href="/legal/privacy">privacy policy</Link>.
      </p>

      <h2>9. Liability</h2>
      <p>
        We are fully liable for intent and gross negligence, for injury to life, body or health,
        under the Product Liability Act, and where we gave a guarantee. For slight negligence we are
        liable only for breach of essential contractual duties (duties whose fulfilment makes the
        contract possible and on which you may rely), limited to the typical, foreseeable damage.
        Otherwise our liability is excluded.
      </p>

      <h2>10. Changes to these terms</h2>
      <p>
        We tell you about changes at least 30 days before they take effect. If you don&apos;t object
        within this time, the new terms apply; we point this out in the notice. If you object,
        either side may cancel the contract.
      </p>

      <h2>11. Final provisions</h2>
      <p>
        German law applies, excluding the UN Convention on Contracts for the International Sale of
        Goods. If you are a merchant, the place of jurisdiction is{" "}
        <Value>[city of our registered office]</Value>. If one clause is invalid, the rest remain
        valid.
      </p>
    </LegalPage>
  );
}
