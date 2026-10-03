# Verification record

Local source verification, 2026-10-03. This file records observed results; CI/browser completion must be tied to the published commit before claiming public verification.

## Executed locally

- 51 Python unit/integration/review tests passed on Python 3.12.14, Linux
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

## Browser status

Local Chromium could not launch because this environment prohibits its process-singleton socket. No sandbox bypass was attempted and no local visual/browser pass is claimed. Both authored browser suites launch Chromium with `chromiumSandbox: true` on Ubuntu 22.04 CI:

- Mock API suite: stale demo/create/poll responses, cancelled late job creation, force/unforce and DPI reruns, error recovery, safe filename rendering, input size/type checks, review-gated export, five viewport widths, external-request detection
- Real backend suite: synthetic PDFs through the bounded worker, correct keep/move/reprint/retire counts, actual front/back PNGs, downloaded ZIP inspection, force/unforce reruns, five viewport widths, screenshots and external-request detection

Screenshots and CI outcomes must be inspected for the published commit. The workflow's existence does not establish they passed. Ubuntu 22.04's announced hosted-runner retirement is April 17, 2027; plan a sandbox-compatible migration.

## Benchmarks, not guarantees

See [raw benchmark JSON](benchmark.json). Simple synthetic vector/text PDFs on this local machine:

- 6 old + 8 new sides, 144 DPI, 4 replacement sides: **1.518 seconds** wall time
- 80 old + 80 changed new sides, 216 DPI, 80 replacement sides, 179,625,600 input pixels: **18.778 seconds**
- Same 80 + 80 sides unchanged, 216 DPI: **12.428 seconds**

Maximum child RSS reported across this benchmark was 44,136 KiB; this is **not aggregate process memory**. Expensive real PDFs can behave differently and fail within the enforced limits. These are no throughput, paper-savings or print-equivalence guarantees.
