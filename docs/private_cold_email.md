# Private imported targets: template and manual email checks

B62 adds two authenticated, provider-free routes:

- `POST /api/private-import-targets/{id}/cold-email/variants`
- `POST /api/private-import-targets/{id}/cold-email/validate`

Each request includes `expected_owner_id`, the reviewed `expected_target_version` (`pwt1:`), `profile`, optional `experience_evidence`, and optional `contact_context`. The context defaults to first contact. Availability can be supplied only through the existing confirmed availability input. Referral, follow-up and paper-reading input are not supported here. `engine` defaults to `template`; `ai` returns `409 private_email_ai_unavailable` and never calls a provider.

Every request authenticates and rereads the active owned target through the private context resolver. A deleted, missing, changed or wrong-owner target is refused. The response carries the exact private context, owner, target ID, source version and writing version. It does not construct a public Opportunity or claim official source verification. Responses and errors use private/no-store headers.

## Template

The one editable draft uses the student's supplied name, the complete imported title explicitly quoted as a saved note, and at most one complete currently confirmed experience. It does not infer a professor title, recruiting status, eligibility, publication, lab relationship, recipient or attachments. The template asks whom to contact and which application process to follow.

Experience selection uses the existing current-source and activity-reference checks. Withdrawn, rejected, unconfirmed, stale-source and ambiguous activity entries remain excluded. The selection retains the existing 4,000-codepoint/eight-entry material budget. This template selects at most one whole entry in stable input order. Its receipt names only the entry actually inserted. The source activity context stays in the receipt; the template does not attach another activity's title or date. Complete entries that cannot fit are omitted with `experience_template_budget_omission`; no prefix is presented as the full experience. Explicit attachment, completed target reading and eligibility claims are omitted with `private_template_claim_omission`, even if the underlying experience entry is confirmed.

The resulting subject/body must fit the existing editor's 2,000/5,000 UTF-16-unit limits. If the mandatory template cannot fit, the route returns `413 private_email_draft_too_large`; it does not shorten the accepted name or title. The title uses readable quotation marks; line breaks, tabs and Unicode line separators become spaces in the email only. Printable content, the saved source and the context receipt remain unchanged. These are local output limits, not model token limits.

## Manual checks and recovery

`validate` additionally accepts exact `subject`, `body`, `recipient` and boolean `contact_requirements_reviewed`. It never returns replacement prose. It checks the fresh writing version, nonblank draft, a single manual email address, the review checkbox, current contact restrictions and the existing finite eligibility/deadline/material/attachment claim rules. Only currently confirmed experience text can support personal GPA/citizenship patterns; raw resume text and target source text cannot supply the student's facts.

The condition checker receives a fixed empty unverified target-condition receipt. No private source or imported metadata enters the public official-evidence helpers. Unsupported target requirement assertions are flagged; questions remain possible. An empty finding list does not verify every factual statement, arbitrary paraphrase, project attribution or real-world eligibility. The manual check intentionally does not impose the public AI draft vocabulary filter on a user's original writing.

`outcome` is `ready` only when the finite checks find no issue; otherwise it is `review_required`. Issues are fixed codes: `empty_draft`, `invalid_recipient`, `contact_review_required`, `contact_blocked`, `unsupported_eligibility_claim`, `unsupported_deadline_claim`, `unsupported_material_claim`, `unsupported_attachment_claim`. Unsupported contact context, invalid input and editor limits return fixed schema codes without the rejected text, arbitrary object keys or validator context.

A detected contact restriction blocks template creation (`409 private_email_contact_blocked`). The same restriction returns `review_required/contact_blocked` for manual validation, leaving the current draft available for correction or offline backup. The checkbox cannot override a block. Unknown contact policy remains unverified after the user checks it; the check records review, not permission.

These endpoints do not send mail, upload attachments or record a send. Historical user-reported contact events keep their separate ledger contract. No live model, real account/DB, hosted service, source website, delivery or writing quality is verified by the offline route tests. B58's existing model excerpt boundary is unchanged; private full-source model forwarding remains unavailable.
