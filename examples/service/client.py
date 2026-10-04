#!/usr/bin/env python3
"""Call `publishing` from a service and turn its exit code into a decision.

    python3 client.py extract sample/hello.html
    PUBLISHING_BIN=publishing python3 client.py convert sample/hello.md -o /tmp/hello.html

Standard library only. The contract it relies on (docs/service.md): stdout is the output path (render
commands: one path per file, or one JSON line with --json), stderr is `publishing: <reason>`, and the
exit code says whose problem it is.
"""
import subprocess
import sys
from pathlib import Path

RUN = str(Path(__file__).with_name("run.sh"))

# 0 done. 1 this document failed: report it to the person who sent it, do not retry.
# 2 the call was wrong: a bug in this service. 3 the toolchain is missing or broken: page the operator.
# 4 (extract only) the file was read and holds no text, e.g. a scanned PDF.
VERDICT = {0: "ok", 1: "bad-document", 2: "bad-call", 3: "operator", 4: "no-text"}


def publishing(*args: str, timeout: int = 300) -> tuple[str, str, str]:
    """Run one command; return (verdict, stdout, stderr). The subprocess timeout is a backstop:
    every subcommand has its own --timeout and stops itself first."""
    try:
        p = subprocess.run([RUN, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "operator", "", "publishing did not return"
    return VERDICT.get(p.returncode, "operator"), p.stdout.strip(), p.stderr.strip()


if __name__ == "__main__":
    verdict, out, err = publishing(*sys.argv[1:])
    print(f"{verdict}: {out or err}")
    sys.exit(0 if verdict == "ok" else 1)
