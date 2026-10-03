# Existing tools and the narrower workflow

Reviewed 2026-10-03. These are product-documentation comparisons, not an exhaustive prior-art search, patent opinion or validated demand study.

- [Bookbinder.js](https://github.com/momijizukamori/bookbinder-js) formats PDFs for bookbinding and supports local/offline use. Imposition already exists; Sheet Patch consumes imposed files rather than replacing their layout tools.
- [pdfcpu Booklet](https://pdfcpu.io/generate/booklet/) arranges logical pages onto duplex sheets with booklet/layout options. Its documentation explicitly describes generated front/back page pairs. Sheet Patch starts after that stage and compares two already-imposed editions.
- [DiffPDF](https://mark-summerfield.github.io/diffpdf.html) compares PDF text or appearance and exports difference reports. Visual comparison itself is established. Sheet Patch connects a strict ordered-pair comparison to one-use old-sheet inventory and an assembly/extraction packet.
- [Acrobat booklet printing](https://helpx.adobe.com/acrobat/desktop/print-documents/booklets-posters-banners/print-booklets.html) documents booklet printing controls, including selected sheet ranges. Manually choosing replacement sheets is an existing workflow; this app does not operate those controls.
- [PDFPress](https://pdfpress.app/home) is adjacent PDF printing/preparation software. Do not infer absent features from its landing page alone.
- [East Coast Blueprints revised-sheet printing](https://ecblueprints.com/print-revised-sheets/) is a direct adjacent service/workflow, not an imposition competitor. The page could not be retrieved reliably in this research pass; no detailed feature claim is made here.

## Product hypothesis

For a small unbound duplex proof or handout stack, the user might benefit from one packet that says where every whole sheet comes from, prevents duplicate reuse of the same physical sheet, extracts both sides of every replacement, and records the rendering assumptions. That integration is this prototype's emphasis. No “first,” “unique,” “patentable,” demand, savings or guaranteed print-equivalence claim is made.

## Non-goals

No printer control, feed-direction inference, imposition, bound-book surgery, mixed-size job repair, arbitrary PDF sanitization, color-managed prepress certification, cloud document ingestion or paid service integration. User validation should measure whether the assembly map is actually easier and safer than manual selected-sheet printing, using synthetic/public documents first.
