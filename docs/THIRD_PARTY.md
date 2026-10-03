# Dependencies

Application Python dependencies are pinned in `requirements.txt`: pypdf 6.10.0 for conservative PDF inspection and whole-page extraction; ReportLab 4.4.9 for synthetic demo PDFs; Pillow 12.3.0 and charset-normalizer 3.5.1 are pinned ReportLab dependencies. The workbench itself is vanilla HTML/CSS/JavaScript with no runtime npm dependency and no remote resources.

Poppler `pdftoppm` is installed separately through the user's OS package manager. It is intentionally **not bundled**. The exact runtime version is written into every plan; this source archive does not lock distribution-level Poppler, Fontconfig or fonts. Consequently reruns on a different rendering environment can produce different raster hashes. Local reference verification uses Poppler 25.03.0. CI records its distribution version.

Playwright 1.56.0 is a pinned development dependency with npm lockfile; it is not shipped into the browser UI. Install browser dependencies explicitly for development. Preserve Chromium sandboxing.

Dependency projects have their own licenses. This repository does not copy their source or select a license for the original application code. Installation retrieves dependency distributions under their existing terms. No license grant for this repository is implied by these notes.
