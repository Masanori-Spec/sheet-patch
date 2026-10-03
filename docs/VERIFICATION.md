# Verification record

Observed verification, 2026-10-03. Exact tested code commit: [`c6a61766a0d263d81a57420c1c8a31514a50e566`](https://github.com/Masanori-Spec/sheet-patch/commit/c6a61766a0d263d81a57420c1c8a31514a50e566).

## Public CI passed

[Run 37123748419](https://github.com/Masanori-Spec/sheet-patch/actions/runs/37123748419) completed successfully for that exact commit. All three jobs passed:

- Python 3.12: 59 tests, four JS model tests and syntax checks
- Python 3.13: 59 tests, four JS model tests and syntax checks
- Chromium: mock and real-backend browser suites with `chromiumSandbox: true` on Ubuntu 22.04

The real suite exercised synthetic PDFs through the local worker, correct whole-sheet counts and assignments, actual ordered front/back PNGs, downloaded ZIP inspection, force/unforce reruns and five viewport widths. Page requests stayed on loopback. The mock suite covered stale/cancelled asynchronous responses, error recovery, file validation, safe filenames, review-gated export, responsive layout and hidden/focused/scrolled skip-link states.

Actual desktop and mobile screenshots were visually inspected: readable layout, correct PDF side previews, visible Fontconfig environment notices, no floating unfocused skip link and a correctly visible keyboard-focused skip link. Browser artifacts and logs are attached to the linked CI run.

## Executed locally

- 59 Python unit/integration/review tests passed on Python 3.12.14, Linux
- 14,641 exhaustive small old/new sequences checked for maximum matching count, one-use old supply, exact ordered-pair equality, same-position reservation and retire partition
- Separate forced-demand exhaustive cases ensure forced new positions do not consume reusable old supply
- PDF fixtures cover unchanged, changed back, reordered sheets, insertion/deletion, duplicate and blank sheets, swapped sides, geometry difference, forced reprint and no-empty-PDF behavior
- Independent review renders every exported side and its expected source side separately with Poppler and compares the actual PPM bytes
- Deliberately corrupted writer output fails verification before a packet is produced
- Feature, geometry, malformed and pixel-budget rejection; process cancellation, repeated starts, recovery after failure; actual renderer grandchildren terminate on both cancellation and unexpected worker death
- Exact Host/Origin/cross-site checks, no CORS, invalid route/path rejection, request body limits, and real API demo/previews/ZIP download
- Four JS model tests and syntax checks passed
- Synthetic replacement PDF front and revised-back raster images were visually inspected: clean, readable and correctly ordered

The local environment's bundled Poppler emitted Fontconfig cache errors. Those errors were not suppressed. Verification used the installed system Poppler **25.03.0** with a writable temporary Fontconfig configuration/cache and recorded the renderer version. Font substitution can differ from a user's machine; comparison remains within one run. CI uses its OS-distributed Poppler and records that version separately.

## Issues found and corrected

Earlier CI rejected exit-0 `Unable to revert mtime` messages produced by Fontconfig's cache UUID/timestamp-maintenance path. The corrected code recognizes only exact, complete, valid-UTF-8 maintenance lines with absolute paths and preserves them in JSON `environmentNotices` plus visible UI/HTML warnings. Unknown or mixed diagnostics, PDF/font warnings, malformed bytes/control framing, oversized notices and nonzero exits remain fatal. Local injection tests verify the notice is retained while replacement raster verification still succeeds. The successful real-browser screenshots confirm this notice path was exercised in CI.

Screenshots also exposed an unfocused skip link floating over a scrolled page. Zero-area clipping with keyboard-focus restoration corrected it; desktop/mobile focus and scroll regressions passed, and the resulting screenshots were inspected.

Local Chromium launch remains prohibited by this development environment's process-singleton socket restriction. No sandbox bypass was attempted. Browser verification was performed in the successful sandbox-enabled CI run above. Ubuntu 22.04's announced hosted-runner retirement is April 17, 2027; migrate the browser job to another sandbox-compatible runner before then.

## Benchmarks, not guarantees

See [raw benchmark JSON](benchmark.json). Simple synthetic vector/text PDFs on this local machine:

- 6 old + 8 new sides, 144 DPI, 4 replacement sides: **1.518 seconds** wall time
- 80 old + 80 changed new sides, 216 DPI, 80 replacement sides, 179,625,600 input pixels: **18.778 seconds**
- Same 80 + 80 sides unchanged, 216 DPI: **12.428 seconds**

Maximum child RSS reported across this benchmark was 44,136 KiB; this is **not aggregate process memory**. Expensive real PDFs can behave differently and fail within the enforced limits. These are no throughput, paper-savings or print-equivalence guarantees.
