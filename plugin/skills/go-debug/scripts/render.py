#!/usr/bin/env python3
"""Build the stepper page from traces.json.

Usage: render.py <stepper.json> [--share <out.html>]

Writes the page named by "out" in stepper.json (default stepper.html) next to
stepper.json, and <name>.version.js beside it. An open page polls that file
and reloads when a new build lands. --share writes a copy without the reload
code instead, for sending to others.

Prints, per scenario, how many of the changed lines in the traced files the
trace ran, so a scenario that misses the change shows up before anyone
opens the page.
"""
import difflib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "stepper.html")


def changed_lines(base_file, head_file):
    """1-based lines of head_file that differ from base_file."""
    with open(head_file) as f:
        head = f.read().split("\n")
    if not os.path.exists(base_file):
        return list(range(1, len(head) + 1))
    with open(base_file) as f:
        base = f.read().split("\n")
    out = []
    for tag, _, _, j1, j2 in difflib.SequenceMatcher(None, base, head, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            out.extend(range(j1 + 1, j2 + 1))
    return out


def load_maybe_file(base, value, as_json):
    if not value:
        return {} if as_json else ""
    if isinstance(value, dict):
        return value
    with open(os.path.join(base, value)) as f:
        return json.load(f) if as_json else f.read()


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    share = None
    if "--share" in args:
        i = args.index("--share")
        share = os.path.abspath(args[i + 1])
        del args[i:i + 2]
    cfg_path = os.path.abspath(args[0])
    base = os.path.dirname(cfg_path)
    with open(cfg_path) as f:
        cfg = json.load(f)
    with open(os.path.join(base, cfg.get("traces", "traces.json"))) as f:
        recorded = json.load(f)
    traces = recorded["scenarios"]

    # Lines that differ from each tree's base, for the files the traces show.
    changed = {}
    for name, t in cfg["trees"].items():
        if not isinstance(t, dict) or not t.get("base"):
            continue
        root, broot = os.path.join(base, t["path"]), os.path.join(base, t["base"])
        files = {f for tr in traces if tr.get("tree", "default") == name for f in tr["src"]}
        changed[name] = {f: changed_lines(os.path.join(broot, f), os.path.join(root, f))
                         for f in sorted(files) if not f.startswith("..")}
        changed[name] = {f: ls for f, ls in changed[name].items() if ls}

    for tr in traces:
        ch = changed.get(tr.get("tree", "default"), {})
        ran = {(s["file"], s["line"]) for s in tr["steps"]}
        parts = []
        for f, ls in ch.items():
            if f in tr["src"]:
                # Count only changed lines inside the functions the trace shows.
                shown = [n for n in ls if str(n) in tr["src"][f]]
                if shown:
                    hit = sum((f, n) in ran for n in shown)
                    parts.append(f"{f} {hit}/{len(shown)}")
        cover = "; changed lines run: " + ", ".join(parts) if parts else ""
        print(f"{tr['id']}: {len(tr['steps'])} steps{cover}", file=sys.stderr)

    out = share or os.path.join(base, cfg.get("out", "stepper.html"))
    version = os.path.splitext(os.path.basename(out))[0] + ".version.js"
    data = {
        "title": cfg.get("title", ""),
        "revision": cfg.get("revision", ""),
        "meta": recorded["meta"],
        "traces": traces,
        "changed": changed,
        "notes": load_maybe_file(base, cfg.get("notes"), True),
    }
    with open(TEMPLATE) as f:
        html = f.read()
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    renderers = load_maybe_file(base, cfg.get("renderers"), False).replace("</script", "<\\/script")
    html = html.replace("/*DATA*/null", blob, 1)
    html = html.replace("/*RENDERERS*/", renderers, 1)
    html = html.replace('/*VERSION_JS*/"stepper.version.js"', json.dumps(version), 1)
    if share:
        html = re.sub(r"<!--LIVE-->.*?<!--/LIVE-->\n?", "", html, flags=re.S)
    with open(out, "w") as f:
        f.write(html)
    if not share:
        with open(os.path.join(os.path.dirname(out), version), "w") as f:
            f.write(f"window.__stepperBuild = '{time.time_ns()}';\n")
    print(f"wrote {out} ({len(html) // 1024} KiB)", file=sys.stderr)


if __name__ == "__main__":
    main()
