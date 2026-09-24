/* How the desk explains a refusal, and where a document came from.

Both are decisions rather than rendering, so they are here where they can be checked
against every case rather than only the one a person happened to click through. */

/* A guard the desk enforces before anything is sent, marked so it is not mistaken for a
   request that failed. Nothing left the browser, so there is nothing to retry: what the
   guard asks for — a revision saved, a recovery finished — is the whole of the answer. */
import {t} from './i18n.js';

export const LOCAL = 'local';

export function refusal(text) {
  return Object.assign(new Error(text), {status: LOCAL});
}

/* The server has already classified a refusal. 400 is the request being wrong on its
   merits and 409 the workspace having moved on: re-sending the same draft fixes neither,
   so neither offers the save retry. A dropped connection carries no status at all, and
   that is the case retry exists for. */
export function failureKind(status) {
  return status === LOCAL ? 'local' : status === 400 ? 'refused' : status === 409 ? 'stale' : 'failed';
}

export function failureStatus(kind) {
  return {
    local: t('feedback.local'),
    refused: t('feedback.refused'),
    stale: t('feedback.stale'),
    failed: t('feedback.failed'),
  }[kind];
}

/* Provenance reads differently per source. A folder import has no commit to name, and
   printing the missing field is worse than saying where the writing actually came from. */
export function sourceOrigin(source) {
  if (!source || source.origin === 'editor') return t('feedback.origin.editor');
  const where = source.relative_path ? t('feedback.origin.path', {path: source.relative_path}) : t('feedback.origin.unknown');
  if (source.origin === 'folder') return where + '\n' + t('feedback.origin.folder');
  return source.commit ? where + '\n' + t('feedback.origin.commit', {commit: source.commit}) : where;
}

/* One date, worded once. The model decides which date a document has and how it knows
   it — a date recorded in the source, the first save here, or neither — and `date_kind`
   carries that decision. Every surface answers from it, so the shelf, the source reader
   and the genealogy cannot say different things about the same document. The wording is
   read when it is used, so it is always in the language the page was served in. */
export const DATE_KINDS = {
  get source() { return t('date.source'); },
  get created() { return t('date.created'); },
  get unknown() { return t('date.unknown'); },
};

export function dateText(date) {
  return date || DATE_KINDS.unknown;
}

export function dateDetail(date, kind) {
  return date ? date + ' · ' + (DATE_KINDS[kind] || DATE_KINDS.unknown) : DATE_KINDS.unknown;
}
