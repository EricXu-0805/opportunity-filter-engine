import type { Metadata } from 'next';
import MarkdownPreview from '@/components/MarkdownPreview';

export const metadata: Metadata = {
  title: 'Privacy Policy',
  description:
    'How JoinALab collects, uses, stores, and shares your information, including AI-provider processing and your data rights.',
};

const EFFECTIVE_DATE = 'August 1, 2026';

const CONTENT = `# Privacy Policy

**Effective date:** ${EFFECTIVE_DATE}
**Operator:** Guoyi (Eric) Xu, sole proprietor, operating "JoinALab" ("we", "us"), located in Illinois, United States.
**Contact for privacy requests:** eric.guoyi.xu@gmail.com

---

## 1. What this service is

JoinALab helps students discover research, internship, and summer-program opportunities, and helps them prepare application materials (a tailored résumé draft and a draft cold-outreach email). You provide a profile; we match it against a catalog of opportunities and, on request, use AI to draft application materials **that you review and send yourself**. JoinALab does not send emails to professors or programs on your behalf without your explicit action.

## 2. Information we collect

### 2.1 Profile information you provide

Only school, college, major, and academic year are required; everything else is optional and you control whether to provide it.

- **Identity / academic:** name (optional), institution, college, major, academic year.
- **International-student status:** an optional flag indicating whether you are an international student. We use this only to assess which opportunities are realistically open to you (e.g. work-authorization or on-campus constraints). You may leave it blank.
- **Background:** research interests, skills and proficiency levels, coursework, experience level.
- **Links:** LinkedIn and GitHub URLs (optional).
- **Résumé text:** if you upload a PDF résumé, we extract text from it in your browser session to pre-fill skills, coursework, and interests. We store up to ~8,000 characters of extracted résumé text as part of your profile. **The original PDF file is not stored on our servers.** Removing the résumé from your profile clears that text and the coursework it extracted from your current profile, and future matching and generation stop using them. Earlier saved versions of your profile (§4, profile history) still contain the text until you request a full data deletion under §7.
- **Preferences:** the kinds of opportunities you are seeking, search weighting, saved searches, filters.

### 2.2 Activity information

- **Favorites and application tracking:** opportunities you save, and status you set (applied / replied / interviewing / rejected / dismissed).
- **Match feedback:** thumbs-up/down signals you give on matches.
- **Attachments:** files you attach to tracked opportunities (stored under your own private folder; see §4).

### 2.3 Account / authentication information

- JoinALab works **without an account** by default: your browser is assigned an anonymous identifier so your data is private to you.
- If you choose to save your profile across devices, you can sign in by email (magic link) or, when offered, link a Google account. Your email address and any linked-account identifiers are held by our authentication provider (Supabase, §5); they are **not** stored in JoinALab's own application database.

### 2.4 Information collected automatically

Our hosting providers (Vercel, Render) record standard server logs — IP address, browser/user-agent, and the pages or API endpoints requested — for security and reliability. We apply rate limits keyed to IP address to prevent abuse.

### 2.5 Email addresses for optional features

If you ask us to email your matches or favorites to yourself, you provide an email address for that one-off delivery. We pass it to our email provider (Resend) to send the message and do not retain it afterward. **One exception:** if you turn on the **weekly email digest** for a saved search, we store that email address in our database (alongside the saved search) until you turn the digest off or delete the saved search, so we can send the recurring email — see §4 and §5.

### 2.6 Product analytics and interest signals

To understand how the product is used and where it falls short, we record a small set of in-product events tied to your anonymous identifier — for example, that you landed on the site, generated matches, opened an opportunity, used an AI feature, or clicked the "apply for me" help. These events are stored in our database (Supabase, §5); we do not sell them or use them for advertising. If you register interest in paid "apply for me" help, we also store the email address you provide for that, so we can contact you, until you ask us to remove it.

We do **not** knowingly collect government identifiers, financial-account numbers, precise geolocation, health data, or biometric data.

### 2.7 Feedback you send us

If you use the in-app feedback widget to send a comment, bug report, or suggestion, we store the message text you submit — and the email address you optionally provide for a reply — tied to your anonymous identifier, in our database (Supabase, §5). We use it solely to read, understand, and act on your feedback; we do not sell it or use it for advertising. Please don't include sensitive personal information in a feedback message.

## 3. How we use your information

- To **match** your profile to opportunities and explain why each matched.
- To **draft application materials** (résumé tailoring, cold-email drafts) using AI, *at your request, per generation* — see §5 for the AI subprocessors involved.
- To **save** your profile, favorites, tracking, and saved searches so they persist.
- To **send** transactional emails you request (your matches/favorites) and, if you opt in, a recurring weekly email digest for a saved search.
- To **understand and improve** the product — which steps you reach and where people drop off — via in-product analytics events, to follow up if you register interest in paid help, and to read and act on any feedback you send us.
- To **secure and operate** the service (rate limiting, abuse prevention, debugging).

We do **not** sell your personal information, and we do **not** use it for third-party advertising.

## 4. Where your data is stored

- **Your profile, favorites, tracking, saved searches, and match feedback** are stored in a Supabase Postgres database, in rows that are access-restricted to your own identity by database row-level security — other users cannot read your rows. If you enable the weekly email digest for a saved search, the email address you provide for it is stored alongside that saved search until you turn the digest off.
- **Product-analytics events and any paid-help interest you register** (including the contact email you provide) are stored in the same Supabase database, scoped to your own anonymous identity.
- **Attachments** you add to tracked opportunities are stored in Supabase Storage under a folder private to your identity (≤5 MB per file; PDF, common image, DOCX, TXT, Markdown).
- **Profile history:** every time your profile is saved, a copy of it is also appended to a version-history table (profile_versions) in the same database, under the same row-level security. That history is append-only: editing your profile — including removing your résumé from it (§2.1) — updates the current profile but does **not** rewrite or remove earlier versions, which still contain what your profile held at the time. There is no self-serve way to purge that history today; it is removed when you request a full data deletion under §7.
- **In your browser:** your profile and some preferences are also cached in your browser's local storage so the app works smoothly and offline-tolerantly. You can clear this at any time via your browser settings.

## 5. Third parties that process your data (subprocessors)

We rely on the following service providers. We share only what each needs to perform its function.

| Provider | Role | What it receives |
|---|---|---|
| **Supabase** (US) | Authentication, database, file storage | Your profile, favorites, tracking, saved searches, attachments; your email / linked-account identifier for sign-in; a digest email address if you enable a saved-search email digest; product-analytics events; any "apply for me" interest you register (with the contact email you provide); and feedback you submit (with the optional reply email) |
| **Vercel** (US) | Frontend hosting | Standard request logs (IP, user-agent, path) |
| **Render** (US) | Backend hosting | API request contents and server logs |
| **AI language-model provider** — **OpenAI**, **Google (Gemini)**, and/or **Anthropic (Claude)**, reached either directly or through **OpenRouter** (a routing gateway to those providers), depending on configuration. The exact models used are operator-configurable and chosen per task for quality. | Generating résumé and cold-email drafts | The relevant profile fields (e.g. name, year, major, skills, coursework, research interests, your own résumé bullet points, LinkedIn/GitHub URLs) **plus** the opportunity's public details, **only for the specific item you ask us to generate** |
| **Resend** (US) | Sending transactional email | The recipient email address you provide and the content of that email (including the weekly saved-search digest, if you enable it) |
| **GitHub API** | Importing your public GitHub profile (only if you use that feature) | The public GitHub username you enter |
| **Sentry** (US, optional) | Error monitoring | Error diagnostics with personal data masking enabled (request bodies, IPs, and cookies are not captured) |

**Important — AI processing disclosure.** When you ask JoinALab to tailor a résumé or draft a cold email, the relevant parts of your profile (which can include your name, academic details, skills, and your own résumé text) are sent to one of the AI providers named above (OpenAI, Google, or Anthropic, reached directly or through the OpenRouter gateway) to generate that output. These providers process the data under their own terms; we do not control their retention. If you do not want your data processed by an AI provider, **do not use the résumé-tailoring or cold-email features** — the core matching and saving features do not require sending your profile to an AI provider.

## 6. How long we keep your data

- **Account and profile data** is retained until you delete it (see §7) or until your account is closed.
- **Browser local storage** persists in your browser until you clear it.
- **Email content** is not retained by JoinALab after sending; the email provider retains it per its own policy.
- **Server and error logs** are retained by our hosting and monitoring providers per their standard retention windows.

## 7. Your choices and rights

Depending on where you live (including California residents under the CCPA/CPRA), you may have the right to access, correct, delete, or obtain a copy of your personal information, and to not be discriminated against for exercising these rights.

- **Access / view:** your profile, favorites, tracking, and saved searches are visible to you in the app at any time. You can also email your matches and favorites to yourself.
- **Correct:** edit your profile in the app at any time.
- **Delete or export:** JoinALab does not yet offer a one-click self-serve delete/export button. **To delete or export all your data, email eric.guoyi.xu@gmail.com from the address or with the account associated with your data, and we will action your request within 30 days.** We will verify the request is genuinely yours before acting.
- **Clear local data:** clear your browser's local storage / site data to remove the locally cached copy.

We do not sell personal information, so there is no "do not sell" action to take.

## 8. Security

- Your stored rows are isolated to your own identity by database row-level security.
- Connections use HTTPS; security headers (HSTS, frame protection, content-type protection) are applied.
- We apply rate limits and per-recipient sending limits to prevent abuse and email bombing, and we sanitize the text that is incorporated into AI prompts to reduce injection and fabrication risks.
- No system is perfectly secure; we cannot guarantee absolute security, but we work to protect your information and to limit what each provider receives.

## 9. International users

JoinALab is operated from the United States and stored with U.S.-based providers. If you access JoinALab from outside the U.S., you understand your information will be processed in the U.S.

## 10. Children

JoinALab is intended for college and university applicants and students. You must be at least 18 to use JoinALab on your own. If you are between 13 and 17, you may use JoinALab only with the consent and involvement of a parent or guardian. JoinALab is not directed to children under 13, and we do not knowingly collect personal information from children under 13.

## 11. Changes to this policy

We may update this policy as the service evolves. We will revise the "Effective date" and, for material changes, take reasonable steps to notify users.

## 12. Contact

Questions or privacy requests: **eric.guoyi.xu@gmail.com**.
`;

export default function PrivacyPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
      <article className="prose prose-sm sm:prose-base prose-gray max-w-none prose-headings:font-semibold prose-h1:text-3xl prose-a:text-indigo-600 prose-table:text-sm">
        <MarkdownPreview>{CONTENT}</MarkdownPreview>
      </article>
    </div>
  );
}
