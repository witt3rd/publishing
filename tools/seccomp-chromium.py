"""Write ci/seccomp-chromium.json: Docker's default seccomp profile plus the three calls
Chromium's namespace sandbox needs (clone and unshare with namespace flags, chroot).

  python3 tools/seccomp-chromium.py

Docker's default profile allows those only to a container holding CAP_SYS_ADMIN (clone,
unshare) or CAP_SYS_CHROOT (chroot), so a non-root container with every capability dropped
cannot start the sandbox and user-content mode refuses to render. The base is moby/profiles at
a pinned commit, checked against its SHA-256; bump both together.
"""
import hashlib
import json
import urllib.request
from pathlib import Path

COMMIT = "2ceae35d351c156cb5a8efc0fdc4a08cf94569d8"
URL = f"https://raw.githubusercontent.com/moby/profiles/{COMMIT}/seccomp/default.json"
SHA256 = "6416b47770785a41ac59073cdc77d9fe98517df2799dc83ef207e622de3053f6"
RULE = {"names": ["clone", "unshare", "chroot"], "action": "SCMP_ACT_ALLOW",
        "comment": "publishing user-content mode: Chromium's namespace sandbox (docs/user-content.md)"}


def main():
    raw = urllib.request.urlopen(URL, timeout=60).read()
    got = hashlib.sha256(raw).hexdigest()
    if got != SHA256:
        raise SystemExit(f"moby default profile: sha256 {got}, expected {SHA256}")
    profile = json.loads(raw)
    profile["syscalls"].append(RULE)
    out = Path(__file__).resolve().parent.parent / "ci" / "seccomp-chromium.json"
    out.write_text(json.dumps(profile, indent=2) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
