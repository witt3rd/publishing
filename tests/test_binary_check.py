"""The repo's PDFs and MP4s sit under docs/ or a declared test-input folder (tools/binary-check.sh)."""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_no_pdf_or_mp4_outside_docs_and_test_inputs():
    r = subprocess.run([str(REPO / "tools" / "binary-check.sh")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
