# Sheet Patch

**A careful second print run, one intact duplex sheet at a time.**

Sheet Patch compares two **already-imposed** PDFs and prepares a reuse-and-replacement packet for an **unbound** stack. Each PDF must be ordered front 1, back 1, front 2, back 2. It treats the ordered front/back pair as indivisible, gives duplicate sheets to at most one destination, and produces a concrete assembly map.

- **Keep** a matching old sheet at the same position
- **Move** another matching whole old sheet to its new position
- **Reprint** both sides when no unused matching pair remains, or when you force reprinting
- **Retire** old sheets that the new stack does not consume

The local browser workbench includes a synthetic revision, front/back thumbnails, explicit force-reprint controls, and a downloadable packet. A CLI uses the same bounded worker and verification path.

> **Raster equality is a reuse candidate, not identical PDF content or guaranteed print output.** Review the original PDFs and physical sheets. Spot colors, overprint, color management, font substitution, subpixel details and printer drivers can differ. This app never operates a printer or infers duplex feed orientation.

## Run locally

Reference platform: **Linux, Python 3.12+, Poppler `pdftoppm`**. Native Windows is unsupported because process groups and POSIX resource limits are required; macOS is not validated. The browser UI is served only at `127.0.0.1`, on a randomly chosen port with a random capability URL.

```sh
# Install poppler-utils from your Linux distribution's package manager first.
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m sheet_patch serve
```

The terminal prints the local URL; `--no-open` avoids automatically opening a browser. Keep that URL private. Stop with Ctrl+C to remove temporary files. Dependencies must be installed in advance; runtime analysis needs no internet connection. Python dependency versions are pinned. Poppler is an explicit OS dependency, not downloaded or silently installed by the app, and its version is recorded in each packet.

### CLI and synthetic demo

```sh
python -m sheet_patch demo --out demo-input
python -m sheet_patch plan demo-input/old.pdf demo-input/new.pdf --out demo-packet
# Force new sheet 1 to reprint, despite a raster match:
python -m sheet_patch plan demo-input/old.pdf demo-input/new.pdf --out forced-packet --dpi 144 --force 1
```

Output directories must not exist. Source PDFs are never edited. The demo maps three old sheets to four new sheets: keep 1, move old 3 to new 2, reprint new 3 (changed back) and new 4 (inserted), retire old 2.

## What the packet contains

- `replacement.pdf`: only the required **complete front/back pairs**, in ascending new-sheet order; omitted when nothing needs printing
- `plan.json`: hashes, exact mapping, force decisions, renderer details and verification evidence
- `assembly.html`: printable, self-contained instructions with no script, external fonts or remote resources
- `packet.zip`: the three applicable files together

Every exported replacement side is independently rerendered during that run and compared with the corresponding new-source fingerprint. This checks extraction fidelity under that renderer and DPI; it does not certify a printer or prove PDF semantic identity. Originals and thumbnails are not included in the packet. Packet files contain source filenames and document fingerprints; share them only where appropriate.

Before moving anything, label each old physical sheet with its original number. Assemble the new stack in row order, taking exactly one intact old or replacement sheet for each row. Retire unused sheets after checking the finished stack. Determine printer settings and feed orientation outside this app, using a safe proof.

## Supported PDF envelope

Conservative MVP acceptance rules deliberately reject rather than silently flatten or discard unsupported features:

- Two nonempty PDFs, each at most **16 MiB**, **2–80 sides**, with an even side count
- One fixed sheet size per document; old and new sizes may differ, but then those pairs cannot match
- All Media/Crop/Trim/Bleed/Art boxes identical, with origin `(0,0)`; width/height **36–2000 points**
- No `/Rotate`, non-default `/UserUnit`, encryption, annotations, forms, optional content/layers, active actions, signatures, attached/associated files, output intents, viewer preferences, Type 3 fonts or external stream data
- **72, 144 or 216 DPI**; at most **20 million pixels per side** and **200 million input pixels** over both documents; export verification adds the replacement sides' pixels
- Object traversal limited to 100,000 indirect objects and depth 100; decoded page/Form/tiling-pattern content limited to 32 MiB and 1,000,000 operators per content stream

The worker has a **180-second wall deadline**. Each process inherits a **120-second CPU limit**, **1.5 GiB address-space limit**, **64 MiB individual file limit**, and 64-open-file limit. Each renderer invocation also has a 25-second deadline. CPU and memory limits are per process, **not** aggregate across worker, renderer, server and browser. Smaller inputs can still be rejected if unusually expensive, malformed or unsupported. Known Fontconfig timestamp-maintenance notices are preserved in the UI and packet; other renderer diagnostics and nonzero exits fail closed. See [security](docs/SECURITY.md) and [verification](docs/VERIFICATION.md).

## How matching works

Each side is rendered sequentially to RGB with Poppler and hashed with its geometry, raster dimensions and DPI. Ordered side hashes form a sheet key. First reserve same-position equal pairs, excluding forced destinations. Then assign remaining equal old pairs in ascending old-sheet order. A forced destination does not consume an old sheet; that sheet can satisfy another destination.

Within this exact raster-key model, the assignment maximizes reused sheet count, including duplicates. It does not optimize handling effort or examine whether a physical sheet is damaged. [Algorithm and invariants](docs/ALGORITHM.md)

## Verification and development

```sh
python -m unittest discover -s tests -v
node --test web/ui-tests/model.test.mjs
npm ci --ignore-scripts
npm run test:browser
npm run test:browser:real
python scripts/benchmark.py --out docs/benchmark.json
```

Node is only needed for UI tests. Playwright Chromium must be installed for browser tests (`npx playwright install --with-deps chromium`). Chromium sandboxing stays enabled. The GitHub workflow uses Ubuntu 22.04 for browser compatibility; that hosted runner is scheduled to retire April 17, 2027, so migrate the browser job before then.

Tests include 14,641 exhaustive small duplicate-matching cases, force-reprint supply checks, changed-back/swapped-side/blank/geometry cases, an independent exported-raster check, feature/malformed/resource rejection, process cancellation/repeat, and loopback host/origin/path safeguards. See [verification status](docs/VERIFICATION.md) for what has actually run, rather than treating the presence of a CI workflow as a passing result.

## Why this project exists

Imposition tools, PDF visual comparison, selected-sheet printing and revised-sheet print services already exist. This prototype explores a narrower workflow: **a finished ordered-duplex reuse packet for an already-printed, unbound stack**, including duplicate supply accounting and a complete-pair replacement PDF. This is a product hypothesis, not a novelty, patentability or market-demand claim. [Prior art and scope](docs/PRIOR_ART.md)

No software license has been selected for this repository. Dependencies retain their respective licenses; see [third-party notes](docs/THIRD_PARTY.md).
