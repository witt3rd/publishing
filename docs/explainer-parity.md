# Explainer parity with the house exemplar

Issue #46. The sample deck (`docs/samples/house-style-explainer-v1`) is the generator's reference; the house
exemplar is `prospecta-explainer-v1.pdf` (a 54-page content deck, kept outside the repo). To compare them:

    tools/parity-grid.sh /mnt/nasty/OneDrive/roger/Documents/Prospecta/prospecta-explainer-v1.pdf \
        ~/Documents/Publishing/explainer-parity-grid.pdf

It rasterises both PDFs (`pdftoppm`, 54 dpi) and joins like kinds side by side (sample left, exemplar right) with
ImageMagick, one page per pair: cover, agenda, statement, diagram, cards, story, map, contrast, two columns,
section, closing. Edit the `pairs` line in the script when the sample's order changes.

Known, deliberate gap: the exemplar's PPTX is page images (the sample's is native, editable text). Since v0.17.0
NotoSans ExtraBold is vendored, and `diagram(callout=)`, `heatmap` and `twocol(outline=True)` cover the exemplar's callout
band, heat-map and good/weak panels.
