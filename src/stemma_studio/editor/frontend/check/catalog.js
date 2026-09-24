/* Tests read the desk in Korean unless they choose otherwise: most assertions were
   written against its Korean wording, and speaking it proves the catalog reaches them. */
import {readFileSync} from 'node:fs';
import {setCatalog} from '../i18n.js';

export function speak(language) {
  setCatalog(language, JSON.parse(readFileSync(new URL('../../../locale/' + language + '.json', import.meta.url), 'utf8')));
}
speak('ko');
