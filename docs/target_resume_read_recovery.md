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

Unsubmitted answers in the full résumé panel, with the chosen activity and the selected answers, are kept in this browser's user-scoped storage, one copy per owner uid and opportunity. They are written as they are typed. Reopening the editor for the same owner and opportunity opens the panel with the answers restored and says so. The truth confirmation is not restored, and restoring submits nothing. Another opportunity or owner starts empty.

The copy is removed when a confirmed save records the answers (answers left unselected are not kept), when recovered answers are explicitly discarded, and when every answer is cleared. An owner change or sign-out sweeps it with the rest of that owner's private browser data, and a write from a superseded owner token is refused. Answers that are kept do not trigger the leave confirmation. Answers too large to keep, a refused write, or answers left after a save still do. There is one copy per owner and opportunity, so when two tabs edit the same supplement the last edit wins. Nothing is sent to the server until the user confirms.
