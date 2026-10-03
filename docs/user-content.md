# User-content mode

The trusted build renders a repository's own sources: Chromium's sandbox off (Playwright's default),
pages loaded from `file://`, no request filter, script on. That is right for a deck in this repo and
wrong for a page made from a person's upload: in v0.1.0 a page with
`<iframe src="file:///etc/passwd">` prints the password file into the PDF, a stylesheet from
`http://10.0.0.1/` is fetched, script runs and a meta refresh is followed.

User-content mode renders a page as if it were hostile. The code is `src/publishing/usercontent.py`;
the proof is `tests/test_usercontent.py` (hostile fixtures) and `tools/usercontent-check.sh` (the same
tests in a locked-down container, run in CI).

## Entries

| Entry | Mode |
|---|---|
| `publishing html PAGE.html -o OUT.pdf` | always user-content: the entry for services |
| `publishing render-html PAGE.html --pdf OUT --png OUTDIR --thumbnail W` | user-content by default: the entry for services that want page images too |
| `publishing render-md NOTE.md ...` and `publishing pdf-pages FILE.pdf ...` | user-content by default (pdf-pages has no other mode) |
| `render-html`/`render-md --trusted` | trusted: the house build's renderer, for a repository's own sources, never a person's; refused under `PUBLISHING_USER_CONTENT=1` |
| `publishing build/check --user-content` | user-content for this run |
| `[user_content] enabled = true` in report.toml | user-content for every build in that repo |
| `PUBLISHING_USER_CONTENT=1` in the environment | user-content for every build; set it in a service's image, where no flag turns it off |
| `publishing build/check` otherwise | trusted, unchanged from v0.1.0 |

`publishing html` options: `--paper letter|a4` (unless the page sets `@page size`), `--allow-js`,
`--max-bytes`, `--max-pages`, `--timeout`, `--max-memory MB`, `--require-netns`, `--json` (one line:
output, pages, the refused requests, `sandboxed`, `netns`). It never overwrites its output. Exit 0 is a
PDF; exit 1 (the render failed) or 2 (usage: an existing output, a bad limit) prints
`publishing: <reason>` and writes nothing.

`render-html` takes the same limits (README "Render"), with `--timeout` covering the whole call, and adds
`--png OUTDIR` (`page-001.png`, ...), `--thumbnail W` (`thumbnail.png`) and `--width`. Its page images are
drawn from the PDF by PDFium in a second supervised child (below); `pdf-pages` runs that child alone on
any PDF; `render-md` makes a person's markdown into the house memo or document in a supervised child,
then renders it as an HTML page whose folder is the markdown's. A sandbox that cannot start is exit 3
there (the host's to fix), not 1.

In a build, user-content mode renders memos and documents. A deck is refused: its `slides.py` is
Python the tool runs, so a deck is trusted by definition. A video is refused too: HyperFrames runs its
HTML and script in a browser outside this sandbox. An SVG is inlined only from inside the
document's folder; anything else stays an `<img>` whose fetch is refused, and the layout lint then
fails the build with "image not found".

## What it does

Each render is its own process tree, supervised by the caller:

1. **Its own process, scrubbed.** The render child gets locale, `PATH`, `HOME`, the browser cache and
   font settings from the environment, never a token. The parent kills the whole tree (found through
   `/proc`, since Chromium leaves the session) at the wall-clock limit or when its private memory
   passes the memory limit.
2. **No network namespace.** Where the host lets an unprivileged user make one, the child runs under
   `unshare --user --net --map-current-user`: a network namespace with no interfaces. Nothing in the
   tree can reach any address. `require_netns` turns "where allowed" into "or fail".
3. **Chromium's sandbox on, verified.** Chromium starts with `chromiumSandbox: true`. Before printing,
   the child checks through `/proc` that every renderer process sits in its own user or pid namespace
   and that no process carries `--no-sandbox`; otherwise it fails. Where the sandbox cannot start,
   Chromium itself refuses to launch. The mode never falls back to no sandbox.
4. **No `file://` at all.** The page is served from the virtual origin `http://publishing.invalid`:
   `/doc/` is the document's own folder and `/_theme/` the house theme (public static files). Chromium
   refuses `file://` from an `http` page. A request is served only when its path, with no `..`, empty
   or hidden (`.name`) part, resolves (symlinks included) to a regular file inside its folder.
5. **A request filter.** Every other request (any host, any port, any other path) is refused. The first
   navigation loads the page; every later navigation (a meta refresh, a frame, a form) gets an empty
   `204`, so the page stays where it is. WebSockets are held as mocks that never connect. Service
   workers and downloads are off.
6. **A second, independent filter.** The page is served with a Content-Security-Policy:
   `default-src 'none'`, images, styles, fonts and media from the origin or `data:`, no frames,
   objects, workers or connections, `base-uri 'self'`, and no script unless allowed.
7. **Backstops.** No host name resolves (`--host-resolver-rules=MAP * ~NOTFOUND`, which also stops
   DNS prefetch), and anything unrouted goes to a proxy that does not exist, loopback included.
8. **No script** unless `allow_js`. With script allowed, the filter, the CSP and the namespace still
   stand, and the time and memory limits stop a loop or a bomb.
9. **Limits.**

| Limit | Default | How |
|---|---|---|
| `max_bytes` | 50 MiB | the page plus every file it loads; checked before launch and per request |
| `max_pages` | 300 | stopped early when the laid-out page is far past it; prints at most `max_pages + 1`, and more than `max_pages` fails |
| `timeout` | 60 s | wall clock of one render, browser start included (a document's contents loop renders up to five times) |
| `max_memory_mb` | 2048 | private resident memory (resident minus shared pages) of the whole tree, polled every 0.1 s |

A typical page renders in under a second with about 125 MB of private memory.

10. **Page images in their own child.** `render-html --png/--thumbnail`, `render-md` and `pdf-pages`
    draw pages with PDFium (pinned by pypdfium2, the engine Chromium shows PDFs with) in a second
    process tree under the same supervisor: the time limit (what is left of the call's), the memory
    limit, the scrubbed environment and the network namespace. It reads its own copy of the PDF and
    writes only into its own temporary folder. Before drawing it refuses a PDF over `max_bytes`, past
    `max_pages`, or with a page whose image would pass 40 megapixels (a 1 x 14400 pt sliver is a
    valid PDF and, at 1400 px wide, an image 20 million pixels tall). Forms and PDF script never run (PDFium's
    form environment is not started).
11. **Markdown in its own child.** `render-md` parses and highlights a person's markdown in a
    supervised child too (time, memory, no network, no secrets), so a pathological input cannot
    hold the caller; inline SVGs come only from inside the folder, as in a build.

## Containers

Chromium's sandbox needs unprivileged user namespaces: the container must let a non-root process call
`clone`/`unshare` with namespace flags and `chroot` inside its own namespace. Docker's default seccomp
profile allows those only with `CAP_SYS_ADMIN` or `CAP_SYS_CHROOT`, so under it the render refuses
(proved in CI). Never grant those capabilities, and never run `--security-opt seccomp=unconfined` or
`--no-sandbox`; use the profile `ci/seccomp-chromium.json` instead: Docker's default plus that one rule
(`tools/seccomp-chromium.py` regenerates it from a pinned, checksummed moby profile).

The run flags user-content mode is proved under, and what a service's container (Spire's venue
renderer, the Explainer, media production) must use:

```sh
docker run --rm --user 65532:65532 --cap-drop ALL --security-opt no-new-privileges \
  --security-opt seccomp=ci/seccomp-chromium.json --network none --read-only --tmpfs /tmp \
  --memory 2g --pids-limit 512 -v "$DOC_DIR:/in:ro" -v "$OUT_DIR:/out" \
  IMAGE html /in/page.html -o /out/page.pdf --json
```

`IMAGE` is the toolbox image built from this repo's `Dockerfile` (README "Services"), whose entrypoint
is `publishing`; CI's image job runs this exact command in it, and the same flags with
`render-html /in/page.html --pdf /out/page.pdf --png /out/pages --thumbnail 320 --json`.

| Flag | Why |
|---|---|
| `--user 65532:65532` | non-root; Chromium will not start its sandbox as root |
| `--cap-drop ALL`, `no-new-privileges` | the namespace sandbox needs no capability and no setuid helper |
| `seccomp=ci/seccomp-chromium.json` | Docker's default profile plus `clone`, `unshare` and `chroot` |
| `--network none` | the container has no network either |
| `--read-only --tmpfs /tmp` | Chromium needs a writable `/tmp` only |
| `--memory`, `--pids-limit` | the hard backstops behind the tool's own limits |

What Spire's containers must grant, in one line: a non-root user, the seccomp profile above (user
namespaces allowed, nothing else added), and a writable `/tmp`. Nothing else: no capability, no
network, no Docker socket, no secret, no mount but the document's own folder (read-only) and the
output folder. Give each document its own folder: the folder is everything a page may load.

With user namespaces allowed, the tool also runs in its own network namespace (`netns: true` in the
result); `--network none` is the container's own guarantee on top of it.

### Hosts

The kernel must allow unprivileged user namespaces. Inside Docker this needs no host change, even on
Ubuntu 24.04, whose AppArmor restricts them for unconfined processes
(`kernel.apparmor_restrict_unprivileged_userns=1`): CI's container job runs on such a runner, with the
setting left at 1, and passes. Run directly on an Ubuntu 23.10+ host (not in a container), the sandbox
needs an AppArmor profile granting `userns` to the pinned Chromium binary, or the sysctl set to 0 (what
this repo's host-level CI job does). Arch (roger) and Debian allow them by default.

Playwright publishes no musl build, so user-content mode does not run in an Alpine image (Spire's
venue image): the venue calls a glibc image that carries publishing.

## Residual risks

- **Chromium itself.** A renderer exploit chained with a sandbox escape (most likely a kernel bug
  reached through user namespaces) beats every layer above but the container. The browser is pinned
  with Playwright; a pin that ages collects Chromium security fixes it does not have, so the pin must
  move with Playwright releases.
- **User namespaces widen the kernel's attack surface** for everything in that container. It is the
  price of Chromium's sandbox; the alternative (no sandbox) is worse. gVisor or a VM per render is the
  next step up if that is not acceptable.
- **The namespace is "where allowed".** Without it the browser process has the container's network,
  and the request filter, the CSP and the dead proxy are what stop a fetch. Hence `--network none` on
  the container, or `--require-netns`.
- **Memory is polled**, every 0.1 s, as private resident pages: a burst can overshoot between polls.
  The container's `--memory` is the hard limit.
- **A race on symlinks.** A file is resolved, then read. Content cannot win that race; another
  process writing into the document's folder during the render could.
- **The output is still the page's.** Its text and its links (to any address) are in the PDF. The PDF
  must still be shown sandboxed, and planted text can still steer an agent that reads it.
- **`allow_js` runs a person's script** in the sandboxed renderer, with no network and inside the
  limits; it is more attack surface (V8) than a page without it. Leave it off unless a format needs it.
- **PDFium parses the PDF outside Chromium's sandbox.** The page-image child has the time and memory
  limits and no network, but it is an ordinary process: a PDFium exploit runs with the container's user
  and can read what that user can read. For `render-html` the PDF is Chromium's own output, so it is
  reached only through a Chromium compromise first; `pdf-pages` parses a person's PDF directly. Mount
  only the document's folder (read-only) and the output folder, as above; gVisor or a VM per render is
  the next step up. pypdfium2's PDFium build must move with its releases, like Chromium.
- **`--trusted` is a flag.** Anything that can pass arguments to `render-html` can ask for the house
  renderer. A service's image sets `PUBLISHING_USER_CONTENT=1`, which refuses it.
- **The trusted build is unchanged.** Any build that reaches `publishing build` without the flag, the
  table or the environment variable renders as in v0.1.0. A service sets `PUBLISHING_USER_CONTENT=1`
  in its image.

## Previews: what server-side thumbnails add

Spire's venue draws a PDF artifact's page one in the viewer's browser with pdf.js
(`app/src/components/ui/use-pdf-page.ts`: `pdfjs-dist`, the whole PDF fetched, page 1 drawn to a canvas,
cached per tab), and shows an HTML artifact as a live, scaled `<iframe sandbox="">` under a no-script CSP.
`render-html --thumbnail W` and `pdf-pages --thumbnail W` would make that preview once, on the server:

- **One render per artifact, not per view.** Each card today downloads the whole PDF and pdf.js's worker
  and parses it, on every device and tab; a thumbnail is one small PNG, cacheable by the artifact's hash
  (the same source gives the same bytes).
- **The hostile parse moves off the viewer.** A person's PDF is parsed in every viewer's browser
  (pdf.js has had code-execution bugs, such as CVE-2024-4367); server-side it is parsed once, inside the
  limits, the namespace and the container flags above. An HTML card stops running a person's page in the
  viewer's browser at all.
- **Consumers without a browser.** E-mail, notifications, search results, agents and exports can show a
  preview that pdf.js cannot draw for them.
- **Every page, not only page one,** for a page strip or a review, at a fixed width.

What it costs: a render service with the container flags above (user namespaces through the seccomp
profile), CPU and storage per artifact, and a thumbnail to refresh when the artifact changes. The
client-side pdf.js preview can stay as the fallback while thumbnails are made.
