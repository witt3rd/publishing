# Spire: call `publishing extract` instead of shelling out to markitdown

Replaces the markitdown shell-out in spire-venue `server/graph-drive.ts` (an unpinned
`pip install markitdown`, run with a 60 s timeout and a 32 MiB buffer). Contract: README "Extract".

## What to call

```ts
// before: execFile("markitdown", [path], { timeout: 60_000, maxBuffer: 32 * 1024 * 1024 }) -> stdout
// after (in an image that has the extract profile):
const { stdout } = await execFile("publishing", ["extract", path, "-o", out, "--timeout", "60", "--max-bytes", String(32 * 2**20)]);
const markdown = await readFile(stdout.trim(), "utf8");   // stdout is the output path
```

`out` must not exist (never overwritten): use a fresh path in a per-call temporary folder. The venue
image is `node:22-alpine`; the extract profile does **not** run on Alpine (onnxruntime has no musl
wheel). Either run it as a sidecar/`docker run` of `Dockerfile.extract` (`publishing-extract`, Debian
slim; mount the input read-only and an output folder, `--network none`), or move the venue to a glibc
base. No install at request time: drop the runtime `pip install`.

## Exit codes

0 extracted (stdout: the markdown path); 1 failed (stderr: one message, at most 400 characters); 2 usage (unsupported
type, missing source, output exists); 3 markitdown missing; 4 found no text.

## Behaviour differences

- **Pinned.** markitdown 0.1.8 with every dependency locked, instead of whatever `pip` resolves today.
  The PDF, DOCX, PPTX and XLSX parsers are installed (the bare `pip install markitdown` has none of
  them, so those formats were only extractable if the venue added extras).
- **Empty is an error.** A scanned PDF, or a file with no text, used to yield an empty string; it now
  exits 4 (`found no text`). Treat it as "no text layer", not a crash.
- **File types are allow-listed.** `.pdf .docx .pptx .xlsx .html .htm .csv .json .xml .epub .txt`.
  Everything else exits 2 before any parser runs: images and audio (they need exiftool, speech or an
  LLM), archives, `.doc`/`.xls`/`.ppt`, URLs, YouTube links.
- **No network, ever.** The child cannot open a socket; plugins, LLM description and transcription are
  off. markitdown's remote fetches (URLs, YouTube, Bing) are unreachable.
- **Output is a file, not a stream.** The size cap (default 32 MiB) is enforced while it is written and
  kills the child; `maxBuffer` overflow is replaced by exit 1 and no output file.
- **Timeout** is the same 60 s default, now killing the whole process group.
- **Cost.** Each call starts a fresh interpreter and loads markitdown (about one second, mostly
  magika's model); batch callers should not expect millisecond calls.
