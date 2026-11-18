#!/usr/bin/env python3
"""Check the CI examples of docs/INTEGRATION.md.

Usage: python3 test/examples/check.py

- Each example file appears verbatim in the guide, as a ```yaml block.
- Each example file is valid YAML with the expected job.
- The guide and the examples reference the image only as a release tag.

Needs PyYAML. Exit status: 0 pass, 1 fail.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "INTEGRATION.md"
EXAMPLES = {
    "examples/github-actions.yml": "github-actions",
    "examples/gitlab-ci.yml": "gitlab-ci",
}
IMAGE_RE = re.compile(r"ghcr\.io/xiam/tlaplus-toolchain(:[^\s\"'`]*)?")
RELEASE_REF = ":0.1.0"


def main() -> int:
    failures: list[str] = []
    guide = GUIDE.read_text()
    blocks = re.findall(r"^```yaml\n(.*?)^```$", guide, re.M | re.S)

    for rel, kind in EXAMPLES.items():
        text = (ROOT / rel).read_text()
        if text not in blocks:
            failures.append(f"{rel}: not shown verbatim in {GUIDE.relative_to(ROOT)}")
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as e:
            failures.append(f"{rel}: invalid YAML: {e}")
            continue
        if kind == "github-actions":
            # YAML 1.1 reads the key `on` as True.
            if not ({"on", True} & set(doc)) or "tlc-check" not in doc.get("jobs", {}):
                failures.append(f"{rel}: no `on` trigger or no jobs.tlc-check")
            elif not doc["jobs"]["tlc-check"].get("steps"):
                failures.append(f"{rel}: jobs.tlc-check has no steps")
        else:
            if not doc.get("tlc-check", {}).get("script"):
                failures.append(f"{rel}: no tlc-check job with a script")

    for rel in [GUIDE.relative_to(ROOT).as_posix(), *EXAMPLES]:
        for m in IMAGE_RE.finditer((ROOT / rel).read_text()):
            if m.group(1) != RELEASE_REF and not (m.group(1) or "").startswith(RELEASE_REF + "@"):
                failures.append(f"{rel}: image reference '{m.group(0)}' is not the release form "
                                f"ghcr.io/xiam/tlaplus-toolchain{RELEASE_REF}")

    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)
    if failures:
        return 1
    print(f"examples: {len(EXAMPLES)} CI examples match the guide and parse as YAML")
    return 0


if __name__ == "__main__":
    sys.exit(main())
