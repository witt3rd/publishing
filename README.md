# publishing

Shared house-style publishing toolchain: decks, memos and long documents from markdown/Python to PDF,
with one look, one set of vendored fonts and one pinned Chromium render. Every repo that produces
reports pins a version of this tool and proves in CI that each committed PDF rebuilds from its source.

The rules for captain-facing reports (what a report is, where copies go, naming, versions, the animus
exception) live in `~/Documents/AGENTS.md`. This tool implements them; it does not restate them.

## Install

The tool owns its environment through uv; nothing depends on host Python, Node or fonts.

```sh
uv tool install git+https://github.com/witt3rd/publishing@v0.1.0   # or run any command through uvx
publishing setup                                                     # the pinned Chromium, into the user cache
```

## Use

```sh
publishing new docs/notes/topic-v1 [--format deck|memo|document]   # scaffold a source folder
publishing build [SOURCE...] [--png DIR]   # build PDFs beside their sources (default: all under docs/)
publishing check [PATH...]                 # fail unless every PDF matches a fresh build of its source
publishing publish docs/notes/topic-v1     # copy the PDF to ~/Documents/<folder>/, never overwriting
publishing compare OLD.pdf NEW.pdf -o OUT.pdf --pair 5:7:"A table" --notes notes.md   # before/after deck
publishing html PAGE.html -o OUT.pdf [--json]   # a person's HTML to PDF: always user-content mode
publishing build --user-content [SOURCE...]     # build untrusted memos/documents the same way
```

**User content.** Anything made from a person's content renders in user-content mode: Chromium's
sandbox on, no network, nothing outside the document's own folder, no script, and caps on bytes, pages,
time and memory. `publishing html` always uses it; a build uses it with `--user-content`,
`[user_content] enabled = true` in report.toml, or `PUBLISHING_USER_CONTENT=1` (for a service's
image). The container flags it needs (non-root, `ci/seccomp-chromium.json`, `--network none`) and its
residual risks: [docs/user-content.md](docs/user-content.md). The plain build is for trusted sources.

## Conventions

- **Formats.** `deck`: a folder with `slides.py` defining `TITLE` and `S` (page HTML at 1920×1080; the
  helpers in `publishing.page` give the title page, slides, cards and the numbered question card).
  `memo`: a folder with `memo.md`, portrait. `document`: a folder with `document.md`, long form, with a
  cover, contents with page numbers, a running header and page numbers. A folder with `source.txt` marks a
  PDF built elsewhere. Memos and documents are markdown with flat front matter (`title`, `subtitle`,
  `kicker`, `meta`, `footer`, `paper`), fenced divs (`::: summary`, `::: q`), heading attributes
  (`{#id .newpage}`), pipe tables with a `: caption` line, figures, footnotes and highlighted code.
- **Layout.** `docs/<kind>/<topic>-vN/` holds the sources; `docs/<kind>/<topic>-vN.pdf` sits beside it,
  committed. The folder is the listing: no index files.
- **Config.** `docs/report.toml` holds the pinned version (`publishing = "0.1.0"`), the `project`, the
  repo's private scan words, the `[publish]` folder for each kind, and `[[document]]` entries for markdown
  files with a fixed PDF path (for example a spec rendered to `docs/Spec.pdf`). Its full schema is the
  docstring of `src/publishing/config.py`. A command run with a different version than the pin re-runs
  itself through `uvx` at the pinned tag.
- **Every build** fails, and writes nothing, on a layout problem (content leaving its page or running into
  the footer, a table or figure wider than the column), a host font or a glyph outside the vendored fonts,
  a secret, a host detail (home path, e-mail), a stale day word (`[scan] days`), or a private word.
  A build that would change nothing but the bytes leaves the committed PDF untouched.
- **Check** compares words and page count, not bytes (Chromium's bytes differ run to run).
- **CI.** Copy `ci/reports.yml` into `.github/workflows/`.
- **Versions.** Tags are immutable. A release that changes rendering (theme, fonts, Playwright) is a
  minor bump; a repo adopts it by bumping its pin and running `publishing check`.

## Develop

```sh
uv sync && uv run publishing setup && uv run pytest -q && uv run publishing check
tools/usercontent-check.sh   # the user-content tests in a locked-down container (needs Docker)
```

The fonts are Noto (SIL OFL 1.1, `src/publishing/theme/fonts/OFL.txt`); `tools/vendor-fonts.py`
re-vendors them. MIT licence for the code.
