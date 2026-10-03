# Sheet Patch UI verification

The web UI has no build step and no runtime third-party dependencies. Static assets must be served under the same trailing-slash capability URL as the local API: `index.html`, `styles.css`, `app.js`, `model.js`, and `favicon.svg`.

## Fast checks

```sh
node --check web/app.js
node --test web/ui-tests/model.test.mjs
```

## Browser tests

Use an environment supporting Chromium's sandbox (for example, a non-root Ubuntu 22 CI runner). Install the `playwright` package and its Chromium browser through the official package registry, plus the project's Python requirements and Poppler for the real-service test.

```sh
UI_ARTIFACT_DIR=artifacts/ui node web/ui-tests/browser.test.cjs
UI_ARTIFACT_DIR=artifacts/ui node web/ui-tests/backend.test.cjs
```

- `browser.test.cjs` starts a loopback-only mock API and verifies demo loading, assembly counts, ordered front/back previews, export review gating, force/unforce reruns, DPI invalidation, delayed creation cancellation, stale poll/demo responses, local file replacement, safe filename rendering, PDF size/extension errors, server error recovery, and five responsive widths
- `backend.test.cjs` starts the real Python service, compares its synthetic PDFs, checks rendered previews, downloads and inspects the ZIP packet, verifies force/unforce reruns and five responsive widths
- Both require `chromiumSandbox: true` and fail on unexpected non-loopback page requests
- Both emit desktop and mobile screenshots to `UI_ARTIFACT_DIR`, defaulting to `/tmp/sheet-patch-ui-artifacts`
- Set `CHROMIUM_EXECUTABLE_PATH` only to use a known installed Chromium instead of Playwright's bundled browser; set `PYTHON` if needed
- A browser launch failure due to host sandbox restrictions is a blocked browser check, not a passing test. Do not disable Chromium's sandbox to work around it

The UI processing states guard asynchronous completion with a generation ID. Replaced files clear old previews; changing comparison detail or force selections marks existing results stale, clears review approval, and removes the download URL until a new plan completes. Late creation responses cancel the obsolete job instead of adopting its result.
