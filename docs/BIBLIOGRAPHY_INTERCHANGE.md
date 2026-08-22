# Bibliography interchange

Tarkka supports BibTeX, RIS, and CSL-JSON as bibliography interchange sources. These files are not treated as full-text documents. Each entry is preserved as a source-native bibliography record and then adapted into the existing canonical Work identity pipeline.

## Command-line import

Import one bibliography file into Tarkka's canonical Work catalog with:

```text
tarkka bibliography import references.bib
```

The command accepts the same BibTeX, RIS, and CSL-JSON formats described below, persists through `TARKKA_HOME/works.json` (default `~/.tarkka/works.json`), and prints a deterministic JSON summary containing the source path and SHA-256, record/work counts, and canonical Work IDs and core metadata. Re-importing the same immutable file is idempotent. Import errors are written to stderr and return exit status `2`.

## Identity rules

A bibliography citation key such as `smith2024` is only local to its source file. Tarkka therefore scopes provider-record identity by the SHA-256 digest of the exact byte buffer that is parsed:

`<source-sha256>:<native-source-key>`

This makes re-importing the same immutable file idempotent without treating local citation keys as global identifiers. Duplicate native keys inside one file are rejected as ambiguous. Strong identifiers such as DOI remain eligible for reconciliation across bibliography files and formats through the existing Work identity rules.

One bibliography import is persisted atomically through the Work repository transaction boundary. If any later entry encounters an identity or persistence conflict, earlier entries from the same import are rolled back rather than leaving a partial catalog.

## Preserved and normalized fields

Each `BibliographyRecord` retains:

- source format and native source key;
- source-native entry/item type;
- title;
- authors;
- publication year when recoverable;
- DOI and URL when present;
- the original parsed field mapping in `fields`.

The normalized `DiscoveryRecord` retains the source format, scoped source identity, native source key, entry type, authors, and native fields as provenance metadata. It also maps source-native entry types to a compact canonical `publication_type` vocabulary used by `WorkCatalogService`, while retaining the original entry type separately.

## Supported formats

### BibTeX

The dependency-free parser accepts `.bib` and `.bibtex` files and supports normal entries, `@string` macros, standard month macros, braced and quoted values, nested braces, parenthesis-delimited entries, `#` value concatenation, and percent comments. Escaped percent signs and percent characters inside quoted/braced values remain data.

### RIS

Repeated tags and native continuation formatting are preserved. Semantic fields such as title and author are normalized for canonical use without rewriting their source-native representation. Common real-world whitespace variations around the RIS tag separator are accepted, while records must still be explicitly bounded by `TY` / `ER`.

### CSL-JSON

Single objects, arrays of items, and objects containing an `items` array are accepted. Native item objects are retained intact after JSON decoding. String and numeric item IDs are preserved as source keys, while booleans are not treated as IDs. Each item must include the CSL-required `type`; invalid integer years are treated as unavailable rather than leaking invalid dates into canonical Work objects.

## DOI identity

Across BibTeX, RIS, and CSL-JSON, DOIs supplied explicitly or through a `doi.org` URL are normalized through the same shared identity boundary. DOI URL query/fragment decorations and trailing citation punctuation are not part of the DOI. If an explicit DOI and DOI URL disagree, the entry fails closed rather than silently choosing one identity.

## Fail-closed behavior

Malformed interchange syntax raises `BibliographyParseError`; missing source files raise `FileNotFoundError`; unsupported filename extensions are rejected rather than guessed; empty sources with no importable records are rejected; duplicate source keys are rejected; and conflicting strong identity evidence remains an explicit error. Canonical Work conflicts continue to use the existing Work catalog conflict rules.
