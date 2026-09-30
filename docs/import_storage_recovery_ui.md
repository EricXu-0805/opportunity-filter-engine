# Import writes and damaged-data recovery

The import page and Saved page wait for the local storage transaction result. Save, update and custom removal do not accept repeated clicks while waiting. A result is shown only while its original account and page intent are still current. Starting another import or changing modes invalidates the earlier UI result; it does not cancel a previously authorized write that has already been queued.

Updating an existing import still uses the complete saved entry and new candidate displayed during review. The confirm action never substitutes a newer saved entry. Account, content or deletion conflicts require a new read and review. Storage and coordination failures preserve the candidate and offer a retry.

The saved-import reader distinguishes ready, damaged and unavailable storage. Readable entries from a damaged list remain visible, but all writes pause. The Saved page does not describe an unreadable list as empty and displays removal failures with a retry.

Recovery is an explicit user action:

- **Download original data** captures the damaged string for the current account and downloads a JSON envelope with `format: ofe-imports-recovery-v1` and `raw`. JSON encoding preserves lone surrogate code units as well as ordinary text. The UI only confirms a download request, not that a file was saved successfully.
- **Review reset** freezes the current raw string and account. The second action explicitly clears the entire damaged import list, including readable records in that list. Profile, email and resume data are not reset.
- Reset checks the exact frozen string after acquiring the shared storage lock. Changed data, account changes, missing coordination or write failure are refused. A changed string requires another review. Unavailable storage cannot be reset through this panel.

The private target API client added separately in B60 is not connected to import cards by these changes. Custom targets still cannot enter the existing public-target email/resume flow, comparison or digest by bypassing their gates. `source_excerpt` remains the active AI input-scope producer; this work does not send additional source content to a model.

## Validation scope

Focused component tests exercise the production storage helpers with the repository's queued Web Locks test implementation. Existing actual-route synthetic fixtures still pass through API adapter, Save, update review, persistence reload and favorite card projection. These checks are not live provider, real sending, browser layout or private writing end-to-end evidence. The storage owner separately checks native multi-tab Web Locks.
