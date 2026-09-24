# stemma-graph

A standalone Python package for question-scoped genealogy graphs. The import
name is `stemma_graph`.

It has no runtime dependencies and needs no Stemma, Git, files, data or
interface — if all you want is the graph, this is the only piece you need.

```sh
python3.12 -m venv .venv
.venv/bin/pip install ./packages/stemma_graph
```

Install into a virtual environment rather than a global interpreter. Once the
package is published this becomes `pip install stemma-graph`; until then,
install the directory as above. It is self-contained, so it can also be copied
into another project and installed from there.

To try it without installing anything, from the repository root:

```sh
python3.12 -B scripts/dev.py example
```

## The model

A `Genealogy` is a directed acyclic graph with **one edge per parent/child
pair**; the questions that succession covers live in that edge's `questions`
list, so adding finer questions never multiplies edges. Self-edges and cycles
are refused.

`Node.archived` marks a document retired from future use as material.
`Genealogy.set_archived` returns a new graph, and `confirm_document` takes
`archive_parents` so a parent can be retired as a succession is confirmed.
Retired documents remain in past lineage and in terminal calculations;
`available_documents` lists the ones still usable.

Every change returns a new immutable graph. Nothing is modified in place.

## Versions

The package version is 0.3.0 and the genealogy JSON schema is v3; they version
different things. Similarity graphs and exploration were removed in 0.3.0.

See the repository [README](https://github.com/byeongsuyu/stemma/blob/main/README.md) and
[design notes](https://github.com/byeongsuyu/stemma/blob/main/docs/design.md).
