"""Chunk worker: python -m pro.worker <timeline.json> <f0> <f1> <out.mp4> <enc.json>

Run as a plain subprocess (not multiprocessing) so the editor server module
is never re-imported in the workers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .engine import render_range


def main(argv: list[str]) -> int:
    tl_path, f0, f1, out, enc_path = argv
    tl = json.loads(Path(tl_path).read_text(encoding="utf-8"))
    enc = json.loads(Path(enc_path).read_text(encoding="utf-8"))
    ok, err = render_range(tl, int(f0), int(f1), Path(out), enc, Path(out + ".progress"))
    if not ok:
        sys.stderr.write(err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
