# Bibliography interchange

Tarkka supports BibTeX, RIS, and CSL-JSON as bibliography interchange sources. These files are not treated as full-text documents. Each entry is preserved as a source-native bibliography record and then adapted into the existing canonical Work identity pipeline.

## Identity rules

A bibliography citation key such as `smith2024` is only local to its source file. Tarkka therefore scopes provider-record identity by the SHA-256 digest of the entire bibliography file:

`<source-sha256>:<native-source-key>`

This makes re-importing the same immutable file idempotent without treating local citation keys as global identifiers. Strong identifiers such as DOI remain eligible for reconciliation across bibliography files and formats through the existing Work identity rules.

## Preserved fields

Each `BibliographyRecord` retains:

- source format and native source key;
- entry/item type;
- title;
- authors;
- publication year when recoverable;
- DOI and URL when present;
- the original parsed field mapping in `native_fields`.

The normalized `DiscoveryRecord` retains the source format, scoped source identity, native source key, entry type, authors, and native fields as provenance metadata.

## Supported formats

### BibTeX

The dependency-free parser supports normal entries, `@string` macros, standard month macros, braced and quoted values, nested braces, and `#` value concatenation. `@comment` and `@preamble` are ignored as non-record declarations.

### RIS

Repeated tags are preserved, continuation lines are appended to their preceding tag, and records must be explicitly bounded by `TY` / `ER`.

### CSL-JSON

Single objects, arrays of items, and objects containing an `items` array are accepted. Native item objects are retained intact after JSON decoding.

## Fail-closed behavior

Malformed interchange syntax raises `BibliographyParseError`; missing source files raise `FileNotFoundError`; and unsupported filename extensions are rejected rather than guessed. Canonical Work conflicts continue to use the existing Work catalog conflict rules.
