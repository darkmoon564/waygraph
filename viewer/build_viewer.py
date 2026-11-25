"""Inline viewer/showcase-data.json into viewer/studio.template.html -> viewer/index.html.

Run:  python viewer/build_viewer.py
The result is a single self-contained file that works from file:// or GitHub Pages.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLACEHOLDER = "/*__SHOWCASE_DATA__*/null"


def build() -> Path:
    data = json.loads((HERE / "showcase-data.json").read_text(encoding="utf-8"))
    # Compact JSON; neutralise anything that could close the <script> element.
    payload = json.dumps(data, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    template = (HERE / "studio.template.html").read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit("template placeholder missing")
    out = HERE / "index.html"
    out.write_text(template.replace(PLACEHOLDER, payload), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build())
