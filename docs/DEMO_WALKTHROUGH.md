# Five-minute proof-stack walkthrough

1. Start `python -m sheet_patch serve` and open its private local URL. Select **Try a sample revision**, then **Build sheet plan**. The synthetic old PDF has 3 duplex sheets; the revision has 4.
2. The result should show **2 reuse candidates, 2 whole sheets to print, 1 old sheet to retire**. New sheet 1 keeps old 1. New sheet 2 moves old 3. New sheet 3 replaces B because its back changed. New sheet 4 is inserted D.
3. Select new sheet 2 and inspect the old/new ordered front/back thumbnail pairs. Open the originals at full zoom for actual review: thumbnail equality is insufficient for print decisions.
4. Force new sheet 1 to reprint. The current plan becomes stale and export is disabled. Rebuild: the plan should now have **1 reuse candidate and 3 sheets to print**. Uncheck and rebuild to restore the original plan.
5. After reviewing the candidates and limitations, check the review box and download the packet. `replacement.pdf` has B front, B revised back, D front and D back, in that exact order. The packet also includes printable assembly instructions and JSON provenance.

Use synthetic or public test documents for evaluation. Do not enter private customer, institutional, medical or patent-candidate material into public screenshots or repository tests. No real printing is needed to evaluate the mapping. If you do print, independently validate duplex settings and physical feed orientation with a safe proof.
