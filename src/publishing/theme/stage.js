/* publishing/theme/stage.js — deterministic continuous-stage runtime for HyperFrames.
 *
 * Hooks into `window.__hf.seek(t)` so a video can paint one persistent <canvas> (2D or WebGL)
 * or mutate one persistent SVG from pure functions of `t` (seconds), instead of slide cards.
 * Also provides papertalk-style cue() lookup against `publishing narrate`'s NAME.json word timings,
 * plus easing, smoothstep, and seeded PRNG helpers (no Date, no Math.random).
 */
(function (global) {
  "use strict";

  const WHITE = "#F2EDE4";
  const GOLD = "#D4A84B";
  const INK = "#18181B";
  const BG_DARK = "#000000";

  const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
  const lerp = (a, b, t) => a + (b - a) * t;
  const sstep = (a, b, x) => {
    const t = clamp((x - a) / (b - a || 1e-9), 0, 1);
    return t * t * (3 - 2 * t);
  };
  const ease = (t) => {
    const u = clamp(t, 0, 1);
    return u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
  };
  const easeOut = (t) => 1 - Math.pow(1 - clamp(t, 0, 1), 3);
  const prog = (t, start, dur) => clamp((t - start) / (dur || 1e-9), 0, 1);

  // Deterministic PRNG (mulberry32) so frames rendered out of order are identical.
  function rng(seed) {
    let s = seed >>> 0;
    return () => {
      s = (s + 0x6d2b79f5) >>> 0;
      let t = Math.imul(s ^ (s >>> 15), 1 | s);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const norm = (s) =>
    String(s || "")
      .toLowerCase()
      .replace(/[^a-z0-9'\s]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();

  /**
   * Build a word-cue lookup from `publishing narrate`'s NAME.json (or a single scene's words array).
   *
   *   const { cue, scene } = PublishingStage.makeCues(narrationJson);
   *   const t0 = cue("the corner");           // searches all scenes
   *   const t1 = cue("the corner", "s02");    // searches scene s02 only (returns global seconds)
   *   const t2 = cue("the corner", "s02", 2); // 2nd occurrence (1-indexed)
   */
  function makeCues(meta) {
    const scenes = Array.isArray(meta) ? [{ id: "_", start: 0, words: meta }] : (meta && meta.scenes) || [];
    const byId = new Map(scenes.map((s) => [s.id, s]));

    function findIn(words, phrase, occurrence) {
      const target = norm(phrase).split(" ").filter(Boolean);
      if (!target.length) throw new Error("empty cue phrase");
      const toks = words.map((w) => norm(w.word));
      let seen = 0;
      for (let i = 0; i <= toks.length - target.length; i++) {
        let ok = true;
        for (let j = 0; j < target.length; j++) {
          if (toks[i + j] !== target[j]) {
            ok = false;
            break;
          }
        }
        if (ok) {
          seen++;
          if (seen === occurrence) return words[i].start;
        }
      }
      return null;
    }

    function cue(phrase, sceneId = null, occurrence = 1) {
      if (sceneId !== null) {
        const sc = byId.get(sceneId);
        if (!sc) throw new Error(`unknown scene "${sceneId}" for cue "${phrase}"`);
        const hit = findIn(sc.words || [], phrase, occurrence);
        if (hit === null) throw new Error(`cue "${phrase}" (occurrence ${occurrence}) not found in scene "${sceneId}"`);
        return hit;
      }
      const all = scenes.flatMap((s) => s.words || []);
      const hit = findIn(all, phrase, occurrence);
      if (hit === null) throw new Error(`cue "${phrase}" (occurrence ${occurrence}) not found`);
      return hit;
    }

    const scene = (id) => {
      const sc = byId.get(id);
      if (!sc) throw new Error(`unknown scene "${id}"`);
      return sc;
    };

    return { cue, scene, scenes };
  }

  /**
   * Bind a pure `paint({ t, duration, fps, frame, ctx, canvas })` function to HyperFrames' seek clock.
   * Wraps `window.__hf.seek` (creating a minimal stub if HyperFrames hasn't attached yet) so every
   * frame captured by HyperFrames calls `paint` synchronously with the exact timestamp `t`.
   */
  function mount({ canvas, paint, duration, fps = 30 }) {
    const root = document.getElementById("root");
    const dur = duration ?? Number(root?.dataset.duration || 1);
    const rate = fps ?? Number(root?.dataset.fps || 30);
    const ctx = canvas ? canvas.getContext("2d") : null;

    const renderAt = (t) => {
      const time = clamp(Number(t) || 0, 0, dur);
      const frame = Math.round(time * rate);
      paint({ t: time, duration: dur, fps: rate, frame, ctx, canvas });
    };

    const hook = () => {
      // Official HyperFrames seek protocol: listen for `hf-seek` events carrying `e.detail.time`.
      if (typeof global.addEventListener === "function") {
        global.addEventListener("hf-seek", (e) => {
          const t = e && e.detail && typeof e.detail.time === "number" ? e.detail.time : 0;
          renderAt(t);
        });
      }
      // Also wrap `window.__hf.seek` for direct headless/unit-test driving.
      const hf = (global.__hf = global.__hf || {});
      if (!hf.duration) hf.duration = dur;
      let inner = typeof hf.seek === "function" ? hf.seek.bind(hf) : null;
      const wrapped = function (t, opts) {
        if (inner) inner(t, opts);
        renderAt(t);
      };
      Object.defineProperty(hf, "seek", {
        configurable: true,
        enumerable: true,
        get() {
          return wrapped;
        },
        set(fn) {
          inner = typeof fn === "function" ? fn.bind(hf) : null;
        },
      });
    };

    hook();
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => {
        hook();
        renderAt(0);
      });
    } else {
      renderAt(0);
    }
    return { renderAt };
  }

  global.PublishingStage = {
    WHITE,
    GOLD,
    INK,
    BG_DARK,
    clamp,
    lerp,
    sstep,
    ease,
    easeOut,
    prog,
    rng,
    makeCues,
    mount,
  };
})(typeof window !== "undefined" ? window : globalThis);
