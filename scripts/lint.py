#!/usr/bin/env python3
"""Repository lint for tlaplus-toolchain.

Checks:

1. Every relative Markdown link in the public tree resolves to a file or
   directory of the public tree, and every `#anchor` matches a heading.
2. Optional public-tree rules (a rules file, see below): listed paths are
   excluded from `git archive` output with `export-ignore`, and listed strings
   appear in no public file.

The public tree is the set of files that `git archive` exports: tracked and
untracked (not ignored) files, minus the paths with the `export-ignore`
attribute. Outside a Git work tree, it is every file under the root.

Rules file format, one rule per line, `#` starts a comment:

    ignore <path>     <path> must carry export-ignore and be absent from
                      `git archive HEAD`
    deny <string>     <string> (case-insensitive) must not occur in a public file
    deny-re <regex>   <regex> (Python, case-insensitive) must match no public
                      file content and no public path

Exit status: 0 clean, 1 findings, 2 usage or environment error.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import tarfile
import unicodedata
import urllib.parse
from pathlib import Path

DEFAULT_RULES = "scripts/public-tree.rules"

FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"(`+)(?:(?!\1).)+?\1")
INLINE_LINK_RE = re.compile(r"!?\[(?:[^\]\\]|\\.)*\]\(\s*<?([^)\s>]+)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
REF_DEF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=data,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def in_git_tree(root: Path) -> bool:
    try:
        return git(root, "rev-parse", "--is-inside-work-tree").strip() == b"true"
    except (OSError, subprocess.CalledProcessError):
        return False


def candidate_files(root: Path, use_git: bool) -> list[str]:
    if use_git:
        out = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        names = [p.decode() for p in out.split(b"\0") if p]
        return sorted(n for n in names if (root / n).is_file())
    names = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for f in filenames:
            names.append(os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/"))
    return sorted(names)


def export_ignored(root: Path, paths: list[str]) -> set[str]:
    if not paths:
        return set()
    out = git(root, "check-attr", "-z", "--stdin", "export-ignore", data="\0".join(paths).encode() + b"\0")
    fields = out.split(b"\0")
    ignored = set()
    for i in range(0, len(fields) - 2, 3):
        path, _attr, value = fields[i].decode(), fields[i + 1], fields[i + 2]
        if value not in (b"unspecified", b"unset"):
            ignored.add(path)
    return ignored


def slugify(heading: str) -> str:
    """GitHub-style heading anchor."""
    text = re.sub(r"`([^`]*)`", r"\1", heading)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.strip().lower()
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in "-_" or cat[0] in "LN" or cat == "Mn":
            out.append(ch)
        elif ch == " ":
            out.append("-")
    return "".join(out)


def scan_markdown(text: str) -> tuple[list[tuple[int, str]], set[str]]:
    """Return (links with line numbers, anchors) outside code."""
    links: list[tuple[int, str]] = []
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    fence: str | None = None
    prose: list[str] = []  # one entry per source line; code lines blanked
    for line in text.splitlines():
        m = FENCE_RE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            prose.append("")
            continue
        if m:
            fence = m.group(1)
            prose.append("")
            continue
        h = HEADING_RE.match(line)
        if h:
            slug = slugify(h.group(2))
            n = counts.get(slug, 0)
            counts[slug] = n + 1
            anchors.add(slug if n == 0 else f"{slug}-{n}")
        for a in re.findall(r"<a\s+(?:name|id)=\"([^\"]+)\"", line):
            anchors.add(a)
        stripped = INLINE_CODE_RE.sub("", line)
        prose.append(stripped)
        rm = REF_DEF_RE.match(stripped)
        if rm:
            links.append((len(prose), rm.group(1)))
    # Match inline links over the joined text, so link text may wrap lines.
    joined = "\n".join(prose)
    for lm in INLINE_LINK_RE.finditer(joined):
        links.append((joined.count("\n", 0, lm.start()) + 1, lm.group(1)))
    return links, anchors


def check_links(root: Path, public: list[str]) -> list[str]:
    public_set = set(public)
    public_dirs = {str(Path(p).parent).replace(os.sep, "/") for p in public}
    for d in list(public_dirs):
        while d not in ("", "."):
            d = str(Path(d).parent).replace(os.sep, "/")
            public_dirs.add(d)
    md = [p for p in public if p.lower().endswith(".md")]
    parsed = {}
    for p in md:
        parsed[p] = scan_markdown((root / p).read_text(encoding="utf-8"))
    findings = []
    for p in md:
        links, anchors = parsed[p]
        base = Path(p).parent
        for lineno, target in links:
            if SCHEME_RE.match(target) or target.startswith("//"):
                continue
            path_part, _, frag = target.partition("#")
            path_part = urllib.parse.unquote(path_part.split("?", 1)[0])
            if not path_part:
                dest, dest_anchors = p, anchors
            else:
                rel = path_part[1:] if path_part.startswith("/") else str(base / path_part)
                dest = os.path.normpath(rel).replace(os.sep, "/")
                if dest.startswith("../") or dest == "..":
                    findings.append(f"{p}:{lineno}: link leaves the repository: {target}")
                    continue
                if dest in public_set:
                    dest_anchors = parsed[dest][1] if dest in parsed else None
                elif dest in public_dirs or dest == ".":
                    dest_anchors = None
                    if frag:
                        findings.append(f"{p}:{lineno}: anchor on a directory link: {target}")
                        continue
                else:
                    findings.append(f"{p}:{lineno}: broken link (not in the public tree): {target}")
                    continue
            if frag and dest_anchors is not None and frag not in dest_anchors:
                findings.append(f"{p}:{lineno}: anchor #{frag} not found in {dest}")
    return findings


def parse_rules(path: Path) -> tuple[list[str], list[str], list[str]]:
    ignores, denies, deny_res = [], [], []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kind, _, value = line.partition(" ")
        value = value.strip()
        if kind == "ignore" and value:
            ignores.append(value)
        elif kind == "deny" and value:
            denies.append(value)
        elif kind == "deny-re" and value:
            try:
                re.compile(value)
            except re.error as e:
                print(f"lint: {path}:{lineno}: bad regex: {e}", file=sys.stderr)
                raise SystemExit(2)
            deny_res.append(value)
        else:
            print(f"lint: {path}:{lineno}: bad rule: {raw!r}", file=sys.stderr)
            raise SystemExit(2)
    return ignores, denies, deny_res


def archive_names(root: Path) -> set[str]:
    data = git(root, "archive", "--format=tar", "HEAD")
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        return {m.name.rstrip("/") for m in tar.getmembers()}


def check_rules(root: Path, rules_rel: str, all_files: list[str], public: list[str]) -> list[str]:
    findings = []
    ignores, denies, deny_res = parse_rules(root / rules_rel)
    if rules_rel not in ignores:
        findings.append(f"{rules_rel}: the rules file must list itself as an ignore rule")
    # Declare export-ignore in the root .gitattributes only; the publisher
    # refuses nested export-ignore sources, exported or not.
    for f in all_files:
        if f.endswith("/.gitattributes") and b"export-ignore" in (root / f).read_bytes():
            findings.append(f"{f}: export-ignore must be declared in the root .gitattributes only")
    ignored = export_ignored(root, ignores)
    for path in ignores:
        if path not in ignored:
            findings.append(f".gitattributes: {path} is not export-ignore")
    try:
        exported = archive_names(root)
    except subprocess.CalledProcessError:
        exported = None  # no commit yet
    if exported is not None:
        for path in ignores:
            if path in exported:
                findings.append(f"git archive HEAD: {path} is exported")
    lowered = [d.lower().encode() for d in denies]
    for f in public:
        content = (root / f).read_bytes().lower()
        for d, needle in zip(denies, lowered):
            if needle in content:
                findings.append(f"{f}: contains a denied string: {d}")
    compiled = [(r, re.compile(r, re.IGNORECASE)) for r in deny_res]
    for f in public:
        text = (root / f).read_bytes().decode("utf-8", errors="replace")
        for r, rx in compiled:
            if rx.search(f):
                findings.append(f"{f}: path matches a denied pattern: {r}")
            for lineno, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    findings.append(f"{f}:{lineno}: matches a denied pattern: {r}")
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".", help="repository root (default: .)")
    ap.add_argument("--rules", default=DEFAULT_RULES, help=f"rules file relative to the root (default: {DEFAULT_RULES})")
    ap.add_argument("--require-rules", action="store_true", help="fail when the rules file is missing")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    use_git = in_git_tree(root)
    all_files = candidate_files(root, use_git)
    ignored = export_ignored(root, all_files) if use_git else set()
    public = [f for f in all_files if f not in ignored]

    findings = check_links(root, public)
    if (root / args.rules).is_file():
        if not use_git:
            print("lint: a rules file needs a Git work tree", file=sys.stderr)
            return 2
        findings += check_rules(root, args.rules, all_files, public)
    elif args.require_rules:
        print(f"lint: rules file {args.rules} is missing", file=sys.stderr)
        return 2
    else:
        print(f"lint: no {args.rules}; public-tree rules skipped")

    for f in findings:
        print(f"lint: {f}")
    print(f"lint: {len(public)} public files, {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
