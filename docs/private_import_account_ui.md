# Private import account copies

The import page and browser-saved cards offer **Review account copy** only after the import has a stable browser record. Opening either page never uploads browser imports. The first click reads the account copy; the review shows the frozen browser candidate and, when present, the complete prior account source. A second explicit confirmation creates or updates the account copy.

Browser and account copies remain separate. A successful save records that action; later browser edits do not synchronize automatically. The account copy is labelled as imported content that has not been independently verified. AI input scope uses the normalized account receipt for saved account content; this work does not enable full-source model input.

## Conflict and account safety

- The adoption controller binds the complete local entry, original owner, target identity and account revision. Changes, deletion, account switches and failed writes require a fresh read and a new review.
- A deleted account identity cannot be recreated by simply retrying the same local entry.
- The account list is separate from the existing favorites count, comparison and saved-search controls. It has distinct loading, sign-in, error and empty states. A failed next page keeps already loaded records and offers a page retry.
- Initial authentication inspection is cancellable and has a 30-second deadline. A late result cannot replace a newer request or restore a retired account.
- Account detail is read on request, supports expanding the entire saved source, and offers only safe HTTP(S) source links. The source remains unverified.
- Account deletion requires opening a full detail and confirming the specific revision shown. A conflict requires rereading; the browser copy and existing email/resume material are not deleted. The UI does not treat an uncertain request outcome as a successful deletion.
- Previous-owner list/detail content is hidden at render time, before passive-effect cleanup. Retired reads are aborted and their results are ignored.

## Scope

The account list links to the owner-bound private history page. This batch does not enable the existing custom-card cold-email or resume buttons, comparisons, automatic uploads, or automatic synchronization. Tracker and history resolution are implemented separately and do not make the imported opportunity independently verified.

## Validation

The batch's tests use synthetic imports, real local ownership/storage modules where stated, and mocked account APIs. Native Chromium checks use production components/hooks and the strict SDK with controlled HTTP responses. No production account, database, provider, email, or corpus is written. See `output/mvp-implementation-20260924/sixtyfirst-evidence/import-ui/` in the main checkout for exact commands and results; browser evidence is maintained by the adoption owner.
