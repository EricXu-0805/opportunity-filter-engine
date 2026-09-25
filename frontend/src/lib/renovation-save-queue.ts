import type { RenovationPayload, RenovationSaveResult, StoredRenovation } from './supabase';

export type RenovationQueueState = {
  status: 'idle' | 'saving' | 'saved' | 'unknown' | 'conflict' | 'missing' | 'unavailable';
  current?: StoredRenovation;
};
type Request = { payload: RenovationPayload; expectedRevision: number };

/** One in-flight write. An unconfirmed write is retried verbatim before newer edits. */
export class RenovationSaveQueue {
  private pending: RenovationPayload | null = null;
  private request: Request | null = null;
  private active = true;
  private state: RenovationQueueState = { status: 'idle' };

  constructor(
    private revision: number,
    private readonly commit: (payload: RenovationPayload, revision: number) => Promise<RenovationSaveResult>,
    private readonly notify: (state: RenovationQueueState) => void,
  ) {}

  enqueue(payload: RenovationPayload) {
    if (!this.active) return;
    this.pending = JSON.parse(JSON.stringify(payload));
    if (['idle', 'saved'].includes(this.state.status)) void this.drain();
  }

  retire() { this.active = false; this.pending = null; }

  retry() {
    if (!this.active || !['unknown', 'unavailable'].includes(this.state.status) || !this.request) return;
    void this.drain(this.request);
  }

  /** Only an explicit user choice may replace a conflict baseline. */
  resolveConflict(payload?: RenovationPayload) {
    if (!this.active || this.state.status !== 'conflict' || !this.state.current) return;
    this.revision = this.state.current.revision;
    this.request = null;
    this.pending = null;
    this.publish({ status: 'idle' });
    if (payload) this.enqueue(payload);
  }

  private publish(state: RenovationQueueState) {
    this.state = state;
    if (this.active) this.notify(state);
  }

  private async drain(retry?: Request) {
    const request = retry ?? (this.pending ? { payload: this.pending, expectedRevision: this.revision } : null);
    if (!request || !this.active) return;
    if (!retry) this.pending = null;
    this.request = request;
    this.publish({ status: 'saving' });
    let result: RenovationSaveResult;
    try { result = await this.commit(request.payload, request.expectedRevision); }
    catch { result = { status: 'unknown' }; }
    if (!this.active) return;
    if (result?.status === 'saved' || result?.status === 'unchanged') {
      this.revision = result.current.revision;
      this.request = null;
      if (this.pending) { void this.drain(); return; }
      this.publish({ status: 'saved' });
    } else if (result?.status === 'conflict') {
      this.publish({ status: 'conflict', current: result.current });
    } else if (result?.status === 'missing') {
      this.publish({ status: 'missing' });
    } else if (result?.status === 'unavailable' || result?.status === 'abandoned') {
      this.publish({ status: 'unavailable' });
    } else {
      this.publish({ status: 'unknown' });
    }
  }
}
