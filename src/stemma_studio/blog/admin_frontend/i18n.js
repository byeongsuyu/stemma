/* The desk's wording in the language the author chose.

The server fills each page's fixed text itself and hands its scripts the same
catalog as inert JSON (see stemma_studio/locale). Scripts name messages by key,
so nothing here knows which language it is speaking.

The editor and the publication screens each serve their own copy of this file;
the two must stay identical, and a test checks that they do. */

let messages = {};
export let language = 'en';

export function setCatalog(lang, table) {
  language = lang;
  messages = table;
}

/* One message with its {name} placeholders filled. An unknown key comes back as it
   was given, which is how text saved before keys existed still reads as written. */
export function t(key, params = {}) {
  const text = Object.hasOwn(messages, key) ? messages[key] : key;
  return text.replace(/\{(\w+)\}/g, (whole, name) => Object.hasOwn(params, name) ? String(params[name]) : whole);
}

if (typeof document !== 'undefined') {
  const node = document.getElementById('messages');
  if (node) setCatalog(document.documentElement.lang, JSON.parse(node.textContent));
}
