Mistune 3.0.2 (BSD-3-Clause), vendored Python sources.
The plugin loader resolves the vendored package namespace instead of globally installed mistune.

Source: https://github.com/lepture/mistune/tree/v3.0.2
Wheel SHA-256: `71481854c30fdbc938963d3605b72501f5c10a9320ecd412c121c163a1c7d205`

App-only dependency; no Stemma or graph dependency. No runtime downloads.

## KaTeX 0.18.7

`katex/katex.cjs` is the unmodified `dist/katex.js` from the official npm archive
https://registry.npmjs.org/katex/-/katex-0.18.7.tgz (MIT; see KATEX-LICENSE).
Only the local Node build helper loads it. Readers receive static MathML, not this runtime.
Trust is disabled; invalid/unsupported formulas fail generation. Macro expansion and runtime are bounded.
