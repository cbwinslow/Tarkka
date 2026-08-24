# Research package inspection

Tarkka can inspect resource relationships already observed by native document
parsers without acquiring their targets or claiming that they are canonical
Works. This gives users and agents a bounded view of a paper's supplementary
files, datasets, software, and alternate representations.

```bash
tarkka resources list <document-id> --limit 20
tarkka resources show <document-id> <resource-link-id>
```

`list` returns Work-representation handles, compact source-observation
metadata, and a paginated list of resource links. `show` is the explicit
expansion step: it returns the selected link's preserved native metadata.

The inspection follows this existing provenance chain:

```text
canonical Work -- WorkDocumentLink -- Document -- Artifact
                                           ^
SourceObservation -- ResourceLinkObservation --+
```

The result intentionally does not fetch a URI, infer its identity, create a
canonical Work, or decide whether it is permitted to acquire. Those are
separate policy and application decisions. If a source parser did not preserve
native observations, the command returns a valid empty resource set rather
than fabricating relationships.

Pagination is bounded to 100 items per request with an offset ceiling of
10,000. This keeps agent-facing inspection progressive and predictable.
