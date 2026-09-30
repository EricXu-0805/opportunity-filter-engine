# Review an existing import before updating it

The Saved/Updated badge is shown only when the saved opportunity matches the displayed candidate. A changed saved version instead receives a neutral difference label.

A new result from an already saved source now offers **Review saved import update**. This action reads the saved entry and freezes both it and the new result. The review shows the old/new title, source address, extracted fields, complete expandable source text, AI input scope, and suggestions.

- **Keep saved version** closes the review without writing. The new result remains available.
- **Confirm update** sends the exact reviewed old entry, candidate, and original owner token to `updateCustomImport`. Success uses the returned stored entry, preserves the existing id/imported_at and replaces the opportunity without merging old input-scope claims. Storage also adds updated_at.
- A changed/deleted entry, different source identity, or changed owner is rejected. Confirmation stays disabled until an explicit read of the current saved version starts a new review. If the saved entry cannot be read, rereading returns to the retained new result with an unavailable message, without claiming it was deleted; a later Save is a separate user action.
- Storage failure keeps both displayed versions and allows retry. Switching accounts clears the previous account's result and review rather than exposing them to the new account.
- Every submission, mode switch, reset, and owner change invalidates older request generations. An older response or failure in the same account cannot replace the current result or reviewed candidate.

The interface warns that existing emails and resumes do not change automatically. Current custom imports do not thereby gain access to canonical-target email/resume/Tracker workflows. Updating an import preserves those other browser keys; it does not prove that an existing document is still suitable.

Current imported model input remains `source_excerpt`. A larger saved source is not proof that the model read all of it. The update replaces the candidate as a whole and does not restore old AI completeness claims.

Storage compares the reviewed entry again before writing and checks the write result. As documented by the storage owner, localStorage does not provide an atomic compare-and-swap against arbitrary, uncoordinated tabs; this UI does not claim such a transaction.

Verification uses real storage helpers and actual local API response bodies delivered through mocked HTTP. Both languages cover Save → reimport → review → confirm → module reload → saved-card expansion, with complete new source and unchanged existing material keys. Component tests also cover cancellation, changed/deleted records, owner changes, storage failure, frozen candidates, and reversed response order. No live provider, service, or browser layout is exercised by these tests.
