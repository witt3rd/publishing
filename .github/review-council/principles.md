# publishing principles for the review council

<!--
The law every change to this repo keeps. README.md "Law" points here; this
file is its one source. The review council (.github/workflows/review-council.yml)
reads it, with AGENTS.md if there is one, from the PR's base commit, so a PR
is judged by the law it started from. Only the owner changes this file.
-->

**Owner:** the maintainer, @witt3rd. A finding that contradicts a rule here
is a proposal to the owner, not a finding.

## Principles

Ordered by durability: the first outlast the last.

1. **Reproducible.** Every committed PDF and MP4 rebuilds from its source, and
   `publishing check` proves it in CI: a PDF by its words and page count, an
   MP4 by its source stamp and frames (README "Conventions", "Video"); the
   same source gives the same image bytes (README "Render"). The whole
   toolchain is pinned: `uv.lock`, the Playwright Chromium, HyperFrames'
   `package-lock.json`, office2pdf's and pandoc's checksums, the vendored
   fonts. Flag an unpinned or unchecksummed download, a render that reads the
   clock, the host, the network or a random source, and a committed output
   that no longer matches its source.
2. **User content is hostile.** Anything made from a person's content renders
   in user-content mode (`docs/user-content.md`): Chromium's sandbox on and
   verified, no network, nothing outside the document's own folder, no
   script unless asked, and the caps on bytes, pages, time and memory. Flag a
   path that renders a person's content without it, a cap or a flag
   loosened, a new default to `--trusted`, and a child process that gets a
   token or the network.
3. **One look.** One theme, one set of vendored fonts, one pinned Chromium
   render. A build fails on a host font or a glyph outside the vendored
   fonts. Flag a second theme, a font loaded from the host or the network,
   and a look that a repo can change without a release of this tool.
4. **Immutable tags, versioned rendering.** A tag is never moved or reused. A
   release that changes rendering (theme, fonts, Playwright, HyperFrames) is
   a minor bump; a repo adopts it by bumping its pin and running `publishing
   check` (README "Conventions"). Flag a rendering change shipped as a patch,
   and a version in `pyproject.toml`, the README's install lines and
   `docs/report.toml` that disagree.
5. **One entry, documented contracts.** The CLI is the one entry for people,
   agents, CI and services (README "Services"). Each command's inputs,
   outputs, exit codes and environment, as the README states them, are a
   contract with every repo and service that pins this tool. A change to one
   changes the README section in the same PR.

## Rules in force

- **Report rules live elsewhere.** The rules for captain-facing reports
  (what a report is, where copies go, naming) live outside this repo; the
  README points at them and never restates them.
- **Credits.** Every third-party component is credited in `NOTICE` with its
  licence; a new one adds its line in the same PR.

## Steward

The written law is this file and README.md: "Conventions", each command's
section ("Video", "Convert", "Extract", "Media", "Render", "Services") and
`docs/user-content.md`. Principles 4 and 5 and both rules in force are yours.

## Architect

Principle 5 is yours: a command, a Python entry (`publishing.convert`,
`publishing.renderhtml`, ...) or an exit code whose shape changes, and every
caller the README or the tests name.

## Inspector

Principle 1 is yours: a render that is not the same on every run, a check
that would pass on a stale output, a test that never reaches the changed
line.

## Warden

Principle 2 is yours. Untrusted input: any HTML, markdown, PDF, Office file,
audio or video a person supplies, every request a rendered page makes, and on
CI anything a pull request author controls.
