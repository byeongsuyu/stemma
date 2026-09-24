import {t} from './i18n.js';

/** Serialize autosaves while retaining edits typed during an outstanding request. */
export class WorkBuffer {
  constructor(send, onBackup = () => {}, onStatus = () => {}) {
    this.send = send; this.onBackup = onBackup; this.onStatus = onStatus;
    this.load(null);
  }
  load(work) {
    this.work = work;
    this.data = structuredClone(work || {title: '', body: '', note: '', selections: []});
    this.generation = 0; this.savedGeneration = 0; this.pending = null;
  }
  edit(change) {
    Object.assign(this.data, change);
    this.generation++;
    this.onBackup(this.snapshot());
    this.onStatus(t('editor.status.unsent'));
  }
  snapshot() {
    return {work: this.work, data: structuredClone(this.data)};
  }
  async flush() {
    if (this.pending) return this.pending;
    this.pending = this.drain();
    try { await this.pending; } finally { this.pending = null; }
  }
  async drain() {
    while (this.savedGeneration !== this.generation) {
      this.onStatus(t('editor.status.saving'));
      if (!this.work) this.work = await this.send('/api/works', {});
      const generation = this.generation;
      const data = structuredClone(this.data);
      const saved = await this.send('/api/work', {...data, id: this.work.id, version: this.work.version});
      this.work = saved;
      this.savedGeneration = generation;
      // Server-owned identity/version advance even if newer input remains unsent.
      this.onBackup(this.savedGeneration === this.generation ? null : this.snapshot());
      this.onStatus(this.savedGeneration === this.generation ? t('editor.status.kept') : t('editor.status.saving_new'));
    }
  }
}
