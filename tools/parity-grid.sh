#!/usr/bin/env bash
# Side-by-side page grid: the explainer sample (left) against the house exemplar (right), one PDF page per
# pair of like kinds. See docs/explainer-parity.md. Usage: tools/parity-grid.sh EXEMPLAR.pdf OUT.pdf
set -euo pipefail
ex=${1:?exemplar pdf}; out=${2:?output pdf}
sample="$(dirname "$0")/../docs/samples/house-style-explainer-v1.pdf"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
pdftoppm -r 54 -png "$sample" "$tmp/s"; pdftoppm -r 54 -png "$ex" "$tmp/e"
# sample page:exemplar page:label
pairs="1:1:cover 2:2:agenda 3:3:statement 4:6:diagram 5:48:cards 6:4:story 7:40:map 8:34:contrast 9:16:twocol 10:5:section 12:54:closing"
i=0
for p in $pairs; do
  IFS=: read -r s e label <<<"$p"; i=$((i+1))
  magick \( -background white -fill black -pointsize 26 "label:$label: sample p$s (left)  |  exemplar p$e (right)" \) \
    \( "$tmp/s-$(printf %02d "$s").png" "$tmp/e-$(printf %02d "$e").png" +append \) -background white -gravity West -append +repage \
    "$tmp/g-$(printf %02d $i).png"
done
magick "$tmp"/g-*.png "$out"
