# Ordered-pair model and invariants

Input side `2i` is front `i+1`; side `2i+1` is back `i+1`. These are user-supplied semantics, not detected print orientation. A sheet key is `(frontFingerprint, backFingerprint)`; swapping front/back produces a different key unless the two sides themselves match.

A side fingerprint hashes canonical JSON containing DPI, exact accepted geometry values, raster width/height and RGB mode, a separator, then the RGB bytes. PDF file SHA-256 hashes separately identify the exact sources. Equal side fingerprints are an operational raster-match candidate, not cryptographic proof of PDF semantic equality. No tolerance, OCR, ignored margins or pixel-difference threshold is used.

## Assignment

1. Reserve equal old/new pairs at the same index, unless the new destination is forced to print
2. Queue all unconsumed old indices per sheet key in ascending index order
3. Visit remaining new destinations in ascending order and consume the earliest equal old index, except forced destinations
4. Unassigned/forced destinations become replacement pairs; unconsumed old indices become retire entries

Let `O(k)` count old sheets of key `k`, and `N(k)` count **non-forced** new demands of key `k`. Any solution reuses at most `sum_k min(O(k), N(k))`. Same-position reservation consumes one supply and demand of the same key. This does not reduce the attainable bound for that key. Queues then attain the remaining bound independently per key. Thus this algorithm maximizes the reused count within the exact-key model and prefers every available same-position match. It does not claim a minimum-labor physical rearrangement.

## Required output invariants

- Every new sheet has one row and exactly one source: old sheet or replacement sheet
- Every old sheet is used at most once; used and retired old sets form a disjoint partition
- A reused sheet has the same ordered front/back keys as its new destination
- Replacement sheet numbering is consecutive in ascending new-destination order
- Replacement side count is even and equals twice the replacement row count
- Rerendered replacement side hashes match the corresponding new-source hashes, in order
- No unsupported interactive/layered/external feature is intentionally stripped to make an input pass

Tests combine exhaustive small sequences, separate forced-demand bounds, PDF fixtures and independent output raster checks. Physical condition, duplex printer choices, folding, binding and paper inventory are outside the model.
