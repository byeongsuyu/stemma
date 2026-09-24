import {t} from './i18n.js';

/* The mutable translation draft; immutable variants are written only when a preview is confirmed.
   It is keyed by language, and only the translated side has a body: the original's is its revision. */
export function draftFromFields(revision, fields, original, translation) {
  return {revision,
    [original]:{title:fields.originalTitle,summary:fields.originalSummary},
    [translation]:{title:fields.translationTitle,summary:fields.translationSummary,body:fields.translationBody}};
}
export function importMarkdown(name, bytes) {
  if(!/\.md$/i.test(name)) throw new Error(t('admin.error.md_file'));
  if(bytes.byteLength>2_000_000) throw new Error(t('admin.error.md_size'));
  return new TextDecoder('utf-8',{fatal:true}).decode(bytes);
}

/* Only an explicit edit based on the current memberships can override the server.
   Old recovery records stored a blank default even when the post had a series. */
export function seriesSelection(memberships, saved, available) {
  const baseline = memberships.length > 1 ? 'keep' : memberships[0] || '';
  const sameBase = Array.isArray(saved?.seriesBase) &&
    [...saved.seriesBase].sort().join('\n') === [...memberships].sort().join('\n');
  const valid = ['', 'new', ...(memberships.length > 1 ? ['keep'] : []), ...available];
  return saved?.seriesChanged === true && sameBase && valid.includes(saved.series)
    ? {value:saved.series, changed:true} : {value:baseline, changed:false};
}
