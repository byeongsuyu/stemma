// Render only supplied formulas. No TeX file access, trusted HTML, or network commands.
const fs = require('node:fs');
const katex = require('./vendor/katex/katex.cjs');
const formulas = JSON.parse(fs.readFileSync(0, 'utf8'));
const macros = {};
try {
  process.stdout.write(JSON.stringify(formulas.map(({text, display}) => katex.renderToString(text, {
    displayMode: display, output: 'mathml', throwOnError: true,
    trust: false, strict: 'error', maxExpand: 1000, maxSize: 20, macros
  }))));
} catch (error) {
  process.stderr.write(String(error.message));
  process.exitCode = 1;
}
