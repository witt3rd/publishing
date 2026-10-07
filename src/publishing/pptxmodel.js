() => {
  // The slide DOM as shapes: boxes, text blocks (runs with their styles) and SVG figures, in paint order.
  const px = (v) => parseFloat(v) || 0;
  const col = (s) => {
    const m = (s || '').match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const withA = (c, o) => (c ? { ...c, a: c.a * o } : null);
  const slides = [];
  document.querySelectorAll('.slide').forEach((slideEl) => {
    const S = slideEl.getBoundingClientRect();
    const items = [];
    const R = (r) => ({ x: r.left - S.left, y: r.top - S.top, w: r.width, h: r.height });
    const bg0 = col(getComputedStyle(slideEl).backgroundColor);

    const shadowRing = (cs) => {
      for (const sh of cs.boxShadow.split(/,(?![^(]*\))/)) {
        const c = col(sh), nums = sh.replace(/rgba?\([^)]*\)/, '').trim().split(/\s+/).map(px);
        if (c && nums.length >= 4 && nums[0] === 0 && nums[1] === 0 && nums[2] === 0 && nums[3] > 0) return { color: c, w: nums[3] };
      }
      return null;
    };
    const box = (e, cs, r, o) => {
      const bgc = withA(col(cs.backgroundColor), o);
      const bw = [px(cs.borderTopWidth), px(cs.borderRightWidth), px(cs.borderBottomWidth), px(cs.borderLeftWidth)];
      const bc = [cs.borderTopColor, cs.borderRightColor, cs.borderBottomColor, cs.borderLeftColor].map((c) => withA(col(c), o));
      const rad = [cs.borderTopLeftRadius, cs.borderTopRightRadius, cs.borderBottomRightRadius, cs.borderBottomLeftRadius].map(px);
      const ring = shadowRing(cs);
      const hasBg = bgc && bgc.a > 0, hasB = bw.some((w) => w > 0);
      if (!hasBg && !hasB && !ring) return;
      const g = R(r);
      const same = rad.every((x) => x === rad[0]);
      const radius = same ? rad[0] : 0;
      const uniform = bw.every((w) => w === bw[0]) && bc.every((c) => c && bc[0] && c.r === bc[0].r && c.g === bc[0].g && c.b === bc[0].b);
      if (hasB && !uniform && radius > 0 && hasBg) {
        const big = bw.indexOf(Math.max(...bw));
        items.push({ t: 'rect', ...g, fill: bc[big], radius });
        items.push({ t: 'rect', x: g.x + bw[3], y: g.y + bw[0], w: g.w - bw[1] - bw[3], h: g.h - bw[0] - bw[2],
          fill: bgc, radius: Math.max(0, radius - Math.max(...bw)) });
        return;
      }
      const it = { t: 'rect', ...g, fill: hasBg ? bgc : null, radius };
      if (hasB && uniform && bw[0] > 0) it.line = { color: bc[0], w: bw[0] };
      else if (ring) it.line = ring;
      if (it.fill || it.line) items.push(it);
      if (hasB && !uniform) {
        const strips = [[g.x, g.y, g.w, bw[0]], [g.x + g.w - bw[1], g.y, bw[1], g.h], [g.x, g.y + g.h - bw[2], g.w, bw[2]], [g.x, g.y, bw[3], g.h]];
        strips.forEach(([x, y, w, h], i) => { if (bw[i] > 0 && bc[i] && bc[i].a > 0) items.push({ t: 'rect', x, y, w, h, fill: bc[i], radius: 0 }); });
      }
    };
    const FAM = { 'publishing sans': 'Noto Sans', 'noto sans': 'Noto Sans', 'publishing serif': 'Noto Serif', 'noto serif': 'Noto Serif',
      'publishing mono': 'Noto Sans Mono' };
    const style = (cs, o) => ({
      size: px(cs.fontSize), bold: parseInt(cs.fontWeight, 10) >= 600, italic: cs.fontStyle === 'italic',
      color: withA(col(cs.color), o), spc: cs.letterSpacing === 'normal' ? 0 : px(cs.letterSpacing),
      font: FAM[cs.fontFamily.split(',')[0].trim().replace(/^["']|["']$/g, '').toLowerCase()] || 'Noto Sans',
    });
    const xform = (t, cs) => {
      const tt = cs.textTransform;
      return tt === 'uppercase' ? t.toUpperCase() : tt === 'lowercase' ? t.toLowerCase()
        : tt === 'capitalize' ? t.replace(/\b(\p{L})/gu, (m) => m.toUpperCase()) : t;
    };
    const textItem = (e, cs, seq, o) => {
      const runs = [];
      const flat = (n) => {
        if (n.nodeType === 3) {
          const pcs = getComputedStyle(n.parentElement);
          const pre = pcs.whiteSpace.startsWith('pre');
          const t = xform(pre ? n.textContent : n.textContent.replace(/[\t\n\r ]+/g, ' '), pcs);
          if (t) runs.push({ text: t, ...style(pcs, o) });
        } else if (n.tagName.toLowerCase() === 'br') runs.push({ br: true });
        else n.childNodes.forEach(flat);
      };
      seq.forEach(flat);
      while (runs.length && runs[0].text !== undefined && !runs[0].text.trim()) runs.shift();
      while (runs.length && runs[runs.length - 1].text !== undefined && !runs[runs.length - 1].text.trim()) runs.pop();
      if (!runs.length) return;
      runs[0].text = runs[0].text?.replace(/^ +/, '');
      const last = runs[runs.length - 1];
      if (last.text !== undefined) last.text = last.text.replace(/ +$/, '');
      const rg = document.createRange();
      rg.setStartBefore(seq[0]);
      rg.setEndAfter(seq[seq.length - 1]);
      const rects = [...rg.getClientRects()].filter((r) => r.width > 0 && r.height > 0);
      if (!rects.length) return;
      const U = { l: Math.min(...rects.map((r) => r.left)), t: Math.min(...rects.map((r) => r.top)),
        r: Math.max(...rects.map((r) => r.right)), b: Math.max(...rects.map((r) => r.bottom)) };
      const fs = px(cs.fontSize);
      const lh = cs.lineHeight === 'normal' ? fs * 1.362 : px(cs.lineHeight);
      const hl = rects.reduce((a, r) => Math.min(a, r.height), 1e9);
      const flex = /flex|grid/.test(cs.display);
      const alone = [...e.childNodes].every((n) => seq.includes(n) || (n.nodeType === 3 && !n.textContent.trim()));
      const er = e.getBoundingClientRect();
      const nowrap = cs.whiteSpace === 'nowrap';
      let x = U.l, w = U.r - U.l;
      if (!flex && alone) {
        x = er.left + px(cs.borderLeftWidth) + px(cs.paddingLeft);
        w = er.width - px(cs.borderLeftWidth) - px(cs.borderRightWidth) - px(cs.paddingLeft) - px(cs.paddingRight);
      }
      const align = cs.textAlign === 'center' ? 'c' : (cs.textAlign === 'right' || cs.textAlign === 'end') ? 'r' : 'l';
      if (!nowrap) {
        const slack = w * 0.03;
        if (align === 'l') w += slack; else if (align === 'r') { x -= slack; w += slack; } else { x -= slack / 2; w += slack; }
      }
      items.push({ t: 'text', x: x - S.left, y: U.t - S.top - (lh - hl) / 2, w, h: U.b - U.t + (lh - hl),
        align, wrap: !nowrap, lh, runs, title: e.tagName === 'H1' });
    };
    const pseudo = (e, which, o) => {
      const ps = getComputedStyle(e, which);
      if (ps.content === 'none' || ps.content === 'normal' || ps.display === 'none') return;
      const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
      const abs = ps.position === 'absolute';
      const x = abs ? r.left + px(cs.borderLeftWidth) + px(ps.left) : r.left;
      const y = abs ? r.top + px(cs.borderTopWidth) + px(ps.top) : r.top;
      const op = o * px(ps.opacity === '' ? '1' : ps.opacity);
      const bgc = withA(col(ps.backgroundColor), op);
      if (abs && bgc && bgc.a > 0 && px(ps.width) && px(ps.height))
        items.push({ t: 'rect', x: x - S.left, y: y - S.top, w: px(ps.width), h: px(ps.height), fill: bgc, radius: px(ps.borderTopLeftRadius) });
      const txt = ps.content.replace(/^["']|["']$/g, '');
      if (txt && !/^(counter|attr|url)/.test(txt)) {
        const fs = px(ps.fontSize);
        items.push({ t: 'text', x: x - S.left, y: y - S.top, w: fs * 1.2, h: fs * 1.3, align: 'l', wrap: false, lh: fs * 1.3,
          runs: [{ text: txt, ...style(ps, op) }], title: false });
      }
    };
    const svgItem = (svg, o) => {
      const r = svg.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const clone = svg.cloneNode(true);
      clone.querySelectorAll('text').forEach((t) => t.remove());
      clone.setAttribute('width', r.width);
      clone.setAttribute('height', r.height);
      if (!clone.getAttribute('xmlns')) clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
      const label = svg.querySelector('title')?.textContent || svg.getAttribute('aria-label') || 'Diagram';
      items.push({ t: 'svg', ...R(r), markup: new XMLSerializer().serializeToString(clone), label });
      const vb = svg.viewBox && svg.viewBox.baseVal && svg.viewBox.baseVal.width ? svg.viewBox.baseVal.width : r.width;
      svg.querySelectorAll('text').forEach((t) => {
        const cs = getComputedStyle(t), tr = t.getBoundingClientRect();
        const txt = t.textContent.replace(/\s+/g, ' ').trim();
        if (!txt || !tr.width) return;
        const k = r.width / vb, fs = px(cs.fontSize) * k;
        const st = { ...style(cs, o), size: fs, color: withA(col(cs.fill), o), bold: parseInt(cs.fontWeight, 10) >= 600 };
        items.push({ t: 'text', ...R(tr), align: cs.textAnchor === 'middle' ? 'c' : cs.textAnchor === 'end' ? 'r' : 'l',
          wrap: false, lh: tr.height, runs: [{ text: txt, ...st }], title: false });
      });
    };
    const walk = (e, op) => {
      const cs = getComputedStyle(e);
      const tag = e.tagName.toLowerCase();
      if (cs.display === 'none' || cs.visibility === 'hidden' || ['script', 'style', 'link', 'meta'].includes(tag)) return;
      const o = op * px(cs.opacity === '' ? '1' : cs.opacity);
      if (tag === 'svg') return svgItem(e, o);
      const r = e.getBoundingClientRect();
      if (tag === 'img') {
        items.push({ t: 'image', ...R(r), src: e.currentSrc || e.src, label: e.alt || 'Image' });
        return;
      }
      box(e, cs, r, o);
      pseudo(e, '::before', o);
      let seq = [];
      const flush = () => { if (seq.length) textItem(e, cs, seq, o); seq = []; };
      for (const n of e.childNodes) {
        if (n.nodeType === 3) { if (n.textContent.trim() || seq.length) seq.push(n); }
        else if (n.nodeType === 1) {
          const nt = n.tagName.toLowerCase();
          if ((getComputedStyle(n).display === 'inline' && nt !== 'svg' && nt !== 'img')) seq.push(n);
          else { flush(); walk(n, o); }
        }
      }
      flush();
      pseudo(e, '::after', o);
    };
    [...slideEl.children].forEach((c) => walk(c, 1));
    slides.push({ bg: bg0, items, text: slideEl.innerText });
  });
  return slides;
}
