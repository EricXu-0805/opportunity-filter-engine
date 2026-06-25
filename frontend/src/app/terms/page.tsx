import type { Metadata } from 'next';
import MarkdownPreview from '@/components/MarkdownPreview';

export const metadata: Metadata = {
  title: 'Terms of Service',
  description:
    'The terms governing your use of JoinALab, including your responsibilities when contacting third parties and AI-content disclaimers.',
};

const EFFECTIVE_DATE = 'June 15, 2026';

const CONTENT = `# Terms of Service

**Effective date:** ${EFFECTIVE_DATE}
**Operator:** Guoyi (Eric) Xu, sole proprietor, operating "JoinALab" ("we", "us"), Illinois, United States.
**Contact:** eric.guoyi.xu@gmail.com

By using JoinALab, you agree to these Terms. If you do not agree, do not use JoinALab.

## 1. The service

JoinALab helps students discover opportunities and prepare application materials. It provides matching, explanations, and **AI-assisted drafts** of résumé bullet points and cold-outreach emails. JoinALab is a drafting and discovery tool — **you decide what to send, to whom, and when.**

## 2. Eligibility

You must be at least 18 years old to use JoinALab on your own. If you are between 13 and 17, you may use JoinALab only with the consent and involvement of a parent or guardian. JoinALab is not directed to children under 13. You are responsible for providing accurate information about yourself.

## 3. Your responsibilities when contacting third parties

JoinALab can generate draft emails to professors, labs, and programs. **You are solely responsible for any message you send.** Specifically, you agree:

- to review every AI-generated draft before sending and to correct anything inaccurate;
- not to send false, misleading, harassing, or spam communications;
- not to misrepresent your qualifications, identity, or affiliation;
- to comply with applicable anti-spam laws (e.g. the U.S. CAN-SPAM Act) and the policies of your email provider and the recipient's institution.

JoinALab provides anti-fabrication checks on AI output, but **you remain responsible for the truthfulness and appropriateness of what you send.**

## 4. AI-generated content

AI output can be wrong, incomplete, or generic. JoinALab does not guarantee that any draft, match, or explanation is accurate, complete, or suitable for your purpose. Treat all AI output as a starting point to be reviewed and edited, not as final or authoritative.

## 5. Acceptable use

You agree not to: misuse or attempt to break the service; access other users' data; scrape or overload the service; use JoinALab for unlawful purposes; or use it to send bulk unsolicited email. We may rate-limit, suspend, or terminate access for violations.

## 6. Accounts

JoinALab works without an account by default. If you create one (email or linked Google / GitHub / Microsoft), you are responsible for activity under your account. Authentication is handled by our provider (Supabase).

## 7. Payment, paid features, and refunds

*Applies only once a paid tier is live.*

- Some features may be offered for a fee. Prices and what's included will be shown before you pay. Payments are processed by **Stripe**; we do not store your card details.
- **Free allowance:** 2 free AI generations are provided at no charge; additional generations or concierge fulfillment may require payment.
- **Refunds:** If you are not satisfied with a paid result, email eric.guoyi.xu@gmail.com within 7 days of your purchase for a full refund — no questions asked.
- We may change pricing prospectively; changes will not affect a purchase already made.

## 8. No professional advice; no guarantee of outcomes

JoinALab is not a career-counseling, legal, or immigration-advice service. We do **not** guarantee admission, a position, a reply, an interview, or any other outcome. Opportunity listings are gathered from public sources and may be outdated or inaccurate; verify details with the source before applying.

## 9. Service "as is"

JoinALab is provided "as is" and "as available," without warranties of any kind to the extent permitted by law. We do not warrant that the service will be uninterrupted, error-free, or secure.

## 10. Limitation of liability

To the maximum extent permitted by law, JoinALab and its operator will not be liable for any indirect, incidental, special, consequential, or punitive damages, or for lost opportunities, arising from your use of the service. Our total liability for any claim is limited to the greater of the amount you paid us in the 3 months before the claim or USD $50.

## 11. Termination

You may stop using JoinALab at any time and request deletion of your data (see the Privacy Policy). We may suspend or terminate access for violation of these Terms.

## 12. Changes to these Terms

We may update these Terms; we will revise the "Effective date" and, for material changes, take reasonable steps to notify users. Continued use after changes means you accept them.

## 13. Governing law

These Terms are governed by the laws of the State of Illinois, United States, without regard to conflict-of-laws rules.

## 14. Contact

Questions: **eric.guoyi.xu@gmail.com**.
`;

export default function TermsPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
      <article className="prose prose-sm sm:prose-base prose-gray max-w-none prose-headings:font-semibold prose-h1:text-3xl prose-a:text-blue-600 prose-table:text-sm">
        <MarkdownPreview>{CONTENT}</MarkdownPreview>
      </article>
    </div>
  );
}
