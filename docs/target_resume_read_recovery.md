# Target résumé reads and supplementary source display

## Read recovery

Current résumé, recent history, and a selected historical version share a 30-second read deadline. It includes identity readiness, the storage response and document signature validation. Callers may cancel reads with an AbortSignal. A failed or timed-out read rejects; it is never returned as an absent document.

The full résumé editor cancels reads when it closes, changes owner/target or starts a newer read of the same kind. Late results cannot replace the active editor. Initial read failure offers an explicit retry. The supplementary panel remains mounted across that retry, retaining its current answers. Reload and history failures preserve the editor's current document.

This applies to reads. Saving still uses the existing owner-bound compare-and-swap operation. No write is automatically replayed, and cancellation does not claim that an in-flight save was rolled back.

## Supplementary source display

The project selector and current-materials panel use the existing confirmed/current-source rules. A project can use its current confirmed organization when its title is unavailable. Otherwise it keeps its record ID and displays a numbered review label.

Candidate, withdrawn, rejected, changed-source, and pending-source-check fields show their state instead of presenting the retained value as current. Linked experience text must match the reference ID and revision and remain active. This does not delete old records or attach answers to a different activity.

Source checks use the exact current résumé text. A source change retires the user's earlier truth confirmation; their answer and activity choice are retained. Manual facts do not become pending simply because a résumé digest is being calculated.

## Validation and limits

Local tests cover held identity/storage/signature reads, cancellation, late results, safe retry, source status, exact experience revision and shared email-panel compatibility. These checks use synthetic profiles and storage responses, with no live model, email or database calls.

This change does not prove the quality of a generated résumé, cloud deployment or Word editing fidelity.

## Unsubmitted supplement answers

Unsubmitted answers in the full résumé panel, with the chosen activity and the selected answers, are kept in this browser's user-scoped storage, one copy per owner uid and opportunity. They are written as they are typed, with the id of the editor that wrote them. Closing the editor, leaving the page or unmounting the editor marks the copy closed. Reopening the editor for the same owner and opportunity opens the panel with a closed copy restored and says so. A copy whose editor is still open in another tab is not offered: each open editor keeps its own round and entry id, so two tabs can each confirm their own answers. After a crash or a killed tab the copy was never marked closed; it is restored only if the browser reports, through the Web Locks API, that the lock its editor held is gone. Where that API is unavailable, such a copy is not restored and the next answers typed for that opportunity replace it. The truth confirmation is not restored, and restoring submits nothing. Another opportunity or owner starts empty.

The copy is removed when a confirmed save records the answers (answers left unselected are not kept), when recovered answers are explicitly discarded, when every answer is cleared, and when the user chooses to discard unsaved work at the leave prompt. An editor only removes or closes its own copy. An owner change or sign-out sweeps it with the rest of that owner's private browser data, and a write from a superseded owner token is refused. Answers that are kept do not trigger the leave confirmation. Answers too large to keep, a refused write, or answers left after a save still do. There is one copy per owner and opportunity, so when two open tabs both type answers, the copy holds the last edit; the other tab's answers are then no longer kept, and closing that tab asks first. Nothing is sent to the server until the user confirms.
