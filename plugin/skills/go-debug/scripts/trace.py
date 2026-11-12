#!/usr/bin/env python3
"""Step through Go tests under Delve and record each line with its variables.

Usage: trace.py <stepper.json> [--check] [scenario-id ...]

Each scenario runs one test under `dlv test --headless` with fixed settings,
stops at its entry functions, then steps line by line: into "ours" functions,
out of everything else. At every stop it saves the line, the call stack, the
function's arguments and locals, and the values the calls it just left
returned.

The run and its output are made as repeatable as Go allows:
- the test always runs with -test.count=1 -test.parallel=1 -test.shuffle=off,
  and with GOMAXPROCS=1 unless the config's env sets it;
- map entries are sorted by key, and memory addresses are replaced by labels
  (#1, #2, ...) in the order they first appear;
- the Go and Delve versions and the settings are written into the output.
So two runs of the same code give the same traces.json, unless the code itself
depends on map order, time, randomness or goroutine timing. --check traces
each scenario twice and names the first step where the two runs differ.

Writes traces.json next to stepper.json: {"meta": {...}, "scenarios": [...]}.
With scenario ids it traces only those and keeps the others from the last run.
"""
import collections
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FUNCS = os.path.join(HERE, "funcs.go")
TEST_FLAGS = ["-test.count=1", "-test.parallel=1", "-test.shuffle=off"]
DEFAULT_ENV = {"GOMAXPROCS": "1"}
LOAD = {
    "FollowPointers": True,
    "MaxVariableRecurse": 4,
    "MaxStringLen": 400,
    "MaxArrayValues": 64,
    "MaxStructFields": -1,
}
SKIP_TYPES = ["context.Context", "net/http.RoundTripper"]
RETURN_ARG = 1 << 4  # Delve's VariableReturnArgument flag: a named result


class Dlv:
    def __init__(self, dlv, tree, sc, env, build_flags):
        cmd = [dlv, "test", sc["pkg"], "--headless", "--api-version=2", "--listen=127.0.0.1:0"]
        if build_flags:
            cmd.append("--build-flags=" + build_flags)
        cmd += ["--", "-test.run", sc["run"], *TEST_FLAGS]
        self.proc = subprocess.Popen(cmd, cwd=tree, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, env=env)
        self.out = collections.deque(maxlen=40)
        port = None
        for line in self.proc.stdout:
            self.out.append(line.rstrip())
            m = re.search(r"API server listening at: 127\.0\.0\.1:(\d+)", line)
            if m:
                port = int(m.group(1))
                break
        if port is None:
            raise RuntimeError("dlv did not start:\n" + "\n".join(self.out))
        # Keep reading the test's output, or a chatty test fills the pipe and blocks.
        threading.Thread(target=self._drain, daemon=True).start()
        self.sock = socket.create_connection(("127.0.0.1", port))
        self.buf = ""
        self.dec = json.JSONDecoder()
        self.id = 0

    def _drain(self):
        for line in self.proc.stdout:
            self.out.append(line.rstrip())

    def call(self, method, params):
        self.id += 1
        msg = {"method": "RPCServer." + method, "params": [params], "id": self.id}
        self.sock.sendall((json.dumps(msg) + "\n").encode())
        while True:
            s = self.buf.lstrip()
            if s:
                try:
                    obj, end = self.dec.raw_decode(s)
                    self.buf = s[end:]
                    if obj.get("error"):
                        raise RuntimeError(f"{method}: {obj['error']}")
                    return obj["result"]
                except json.JSONDecodeError:
                    pass
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise RuntimeError("dlv closed the connection")
            self.buf += chunk.decode()

    def command(self, name, load):
        return self.call("Command", {"name": name, "ReturnInfoLoadConfig": load})["State"]

    def close(self):
        try:
            self.call("Detach", {"Kill": True})
        except Exception:
            pass
        self.proc.kill()


def goval(v):
    """Turn a Delve variable into plain JSON, keeping the Go type."""
    t = v.get("type", "")
    kind = v.get("kind")
    ch = v.get("children") or []
    if v.get("unreadable"):
        return {"t": t, "v": "<unreadable>"}
    if t == "[]uint8":
        b = bytes(int(c["value"]) for c in ch if c.get("value") not in (None, ""))
        return {"t": t, "v": b.decode("utf-8", "replace")}
    if kind == 21:  # map
        if v.get("value") == "nil" or (not ch and v.get("len", 0) == 0 and v.get("base", 0) == 0):
            return {"t": t, "v": None, "len": 0}
        items = [[goval(ch[i]), goval(ch[i + 1])] for i in range(0, len(ch) - 1, 2)]
        if (v.get("len") or 0) > len(items):
            # Delve loads the first entries in Go's random map order, so a
            # cut map would show another subset on every run: keep its size.
            return {"t": t, "map": [], "len": v.get("len"), "cut": True, "addr": v.get("base")}
        return {"t": t, "map": items, "len": v.get("len"), "addr": v.get("base")}
    if kind in (17, 23):  # array, slice
        if kind == 23 and v.get("base", 0) == 0:
            return {"t": t, "v": None, "len": 0}
        return {"t": t, "list": [goval(c) for c in ch], "len": v.get("len")}
    if kind == 25:  # struct
        return {"t": t, "fields": [[c["name"], goval(c)] for c in ch]}
    if kind == 22:  # pointer
        if not ch or v.get("value") == "nil" or ch[0].get("addr", 0) == 0:
            return {"t": t, "v": None}
        inner = goval(ch[0])
        inner["ptr"] = ch[0].get("addr")
        return inner
    if kind == 20:  # interface
        if not ch or ch[0].get("kind") == 0:
            return {"t": t, "v": None}
        inner = goval(ch[0])
        inner["iface"] = t
        return inner
    return {"t": t, "k": kind, "v": v.get("value", "")}


def _without_ids(v):
    if isinstance(v, dict):
        return {k: _without_ids(x) for k, x in v.items() if k not in ("addr", "ptr")}
    if isinstance(v, list):
        return [_without_ids(x) for x in v]
    return v


def normalize(steps):
    """Sort map entries by key and replace addresses with labels, in place.

    Go visits a map in a random order and the heap lands at other addresses
    from run to run; neither tells the reader anything. A label stays with an
    address while the address is in sight from step to step, so the page can
    still tell that two names hold one map, or that a pointer moved. Once an
    address is out of sight for a step, Go may hand it to a new object at a
    moment that differs from run to run, so it gets a new label if it shows up
    again.
    """
    live, count = {}, 0

    def walk(v, seen):
        nonlocal count
        if isinstance(v, dict):
            if "map" in v:
                v["map"].sort(key=lambda kv: json.dumps(_without_ids(kv[0]), sort_keys=True))
            for k in ("addr", "ptr"):
                a = v.get(k)
                if a:
                    if a not in live:
                        count += 1
                        live[a] = f"#{count}"
                    seen.add(a)
                    v[k] = live[a]
            for x in v.values():
                walk(x, seen)
        elif isinstance(v, list):
            for x in v:
                walk(x, seen)

    for st in steps:
        seen = set()
        walk([st["args"], st["locals"], st["returned"]], seen)
        live = {a: label for a, label in live.items() if a in seen}


def short_fn(name):
    """github.com/a/b/pkg.(*T).M[go.shape...] -> pkg.(*T).M"""
    return name.split("[", 1)[0].split("/")[-1]


def pkg_prefix(fn):
    """knative.dev/func/pkg/knative.T.M -> knative.dev/func/pkg/knative."""
    head, _, tail = fn.rpartition("/")
    return (head + "/" if head else "") + tail.split(".", 1)[0] + "."


def parse_go(paths):
    """Read the files with funcs.go, Go's own parser.

    Returns {path: [(first, last), ...]} for the top-level funcs, and
    {path: {"decl": {line: last}, "range": {line: first body line}}}: the
    statements that declare variables on line and run on to last, and the
    for-range loops that declare their key and value on line.
    """
    funcs = {p: [] for p in paths}
    decls = {p: {"decl": {}, "range": {}} for p in paths}
    if not paths:
        return funcs, decls
    env = {**os.environ, "GOTOOLCHAIN": "local", "GOFLAGS": "", "GOWORK": "off"}
    p = subprocess.run(["go", "run", FUNCS, "--", *paths], cwd=HERE, capture_output=True, text=True, env=env)
    if p.returncode:
        raise RuntimeError("funcs.go failed:\n" + p.stderr)
    for line in p.stdout.splitlines():
        kind, f, first, last = line.split("\t")[:4]
        if kind == "func":
            funcs[f].append((int(first), int(last)))
        else:
            d = decls[f][kind]
            d[int(first)] = max(int(last), d.get(int(first), 0))
    return funcs, decls


def drop_unassigned(steps, decls):
    """Leave out locals read before they hold a value, in place.

    Delve lists a local from its declaration line on, but until the statement
    that declares it has run, it holds whatever was in memory: a different
    value on every run. At a function's first stop nothing in its body has
    run, not even the capture of a closure's variables or the zeroing of its
    named results, so it shows no locals and no named results.
    Later a local declared on line D, by a statement that runs on to line E,
    shows once the function has gone from D..E to a line outside it. The key
    and value of a for-range loop on line D are copied in at the start of each
    pass, so they never show on D or on the loop's first body line.
    """
    frame_fn, last, done = {}, {}, {}
    prev_depth = 0
    for st in steps:
        depth, line = len(st["stack"]), st["line"]
        spans = decls[st["path"]]["decl"]
        loops = decls[st["path"]]["range"]
        entry = depth > prev_depth or frame_fn.get(depth) != st["fn"]
        if entry:
            frame_fn[depth], last[depth], done[depth] = st["fn"], None, set()
        elif last[depth] not in (None, line):
            p = last[depth]
            for d in [p] + [d for d, e in spans.items() if d <= p <= e]:
                if not d <= line <= spans.get(d, d):
                    done[depth].add(d)
        last[depth], prev_depth = line, depth

        def assigned(decl):
            if entry:
                return False
            if decl in loops:
                return not decl <= line <= loops[decl]
            return not decl <= line <= spans.get(decl, decl) or decl in done[depth]

        st["locals"] = [[n, v] for n, v, decl in st["locals"] if assigned(decl)]
        st["args"] = [[n, v] for n, v, result in st["args"] if not (entry and result)]


def go_version(tree, env):
    p = subprocess.run(["go", "env", "GOVERSION"], cwd=tree, capture_output=True, text=True, env=env)
    return p.stdout.strip() or "unknown"


def run_env(cfg, sc):
    """The env a scenario sets on top of the user's: the fixed defaults, then the config's."""
    return {**DEFAULT_ENV, **cfg.get("env", {}), **sc.get("env", {})}


def build_flags(cfg, sc):
    return sc.get("build_flags", cfg.get("build_flags", ""))


def trace(cfg, tree, sc):
    ours_prefixes = sc.get("ours") or sorted({pkg_prefix(f) for f in sc["entry"]})
    if isinstance(ours_prefixes, str):
        ours_prefixes = [ours_prefixes]
    skip = set(sc.get("skip", []))
    tests = sc.get("include_tests", False)
    skip_types = SKIP_TYPES + cfg.get("skip_types", []) + sc.get("skip_types", [])
    load = LOAD | cfg.get("load", {})
    env = {**os.environ, **run_env(cfg, sc)}

    def is_ours(fn, file):
        return (any(fn.startswith(p) for p in ours_prefixes) and fn not in skip
                and (tests or not file.endswith("_test.go")))

    def keep_var(v):
        if v["name"].startswith(("~", ".")):
            return False
        return not any(s in v.get("type", "") for s in skip_types)

    d = Dlv(cfg["dlv"], tree, sc, env, build_flags(cfg, sc))
    steps, paths = [], set()
    try:
        for fn in sc["entry"]:
            d.call("CreateBreakpoint", {"Breakpoint": {"functionName": fn}})
        state = d.command("continue", load)
        returns, last_fn = [], ""
        guard, limit = 0, cfg.get("max_steps", 3000)
        while not state.get("exited") and guard < limit:
            guard += 1
            th = state.get("currentThread") or {}
            fn = (th.get("function") or {}).get("name", "")
            gid = (state.get("currentGoroutine") or state.get("selectedGoroutine") or {}).get("id", -1)
            rv = [goval(r) | {"name": r.get("name", "")} for r in (th.get("ReturnValues") or [])]
            ours = is_ours(fn, th.get("file", ""))
            if rv and (ours or any(last_fn.startswith(p) for p in ours_prefixes)):
                # Return values belong to the function we just left.
                returns.append({"fn": short_fn(last_fn), "values": rv})
            if not os.path.isfile(th.get("file", "")):
                # A wrapper the compiler wrote ("<autogenerated>"), such as a
                # pointer method calling the value method: no source to show,
                # so step on through it into the real code.
                state = d.command("step", load)
                continue
            if not ours:
                last_fn = fn
                stack = d.call("Stacktrace", {"Id": gid, "Depth": 50})["Locations"]
                if not any(is_ours((f.get("function") or {}).get("name", ""), f.get("file", ""))
                           for f in stack[1:]):
                    break  # left our code for good: one call per scenario
                state = d.command("stepOut", load)
                continue
            path, line = th["file"], th["line"]
            paths.add(path)
            scope = {"GoroutineID": gid, "Frame": 0}
            args = d.call("ListFunctionArgs", {"Scope": scope, "Cfg": load})["Args"]
            locs = d.call("ListLocalVars", {"Scope": scope, "Cfg": load})["Variables"]
            stack = d.call("Stacktrace", {"Id": gid, "Depth": 50})["Locations"]
            calls = [(f.get("function") or {}).get("name", "") for f in stack]
            calls = [c for c, f in zip(calls, stack) if is_ours(c, f.get("file", ""))]
            steps.append({
                "path": path, "line": line, "fn": fn, "stack": calls,
                "args": [[a["name"], goval(a), a.get("flags", 0) & RETURN_ARG] for a in args if keep_var(a)],
                # The declaration line goes until drop_unassigned has used it.
                "locals": [[v["name"], goval(v), v.get("DeclLine", 0)] for v in locs if keep_var(v)],
                "returned": returns,
            })
            # Several stops on one line (a call returned part way) become one step.
            if len(steps) > 1:
                prev, cur = steps[-2], steps[-1]
                if (prev["fn"], prev["line"], len(prev["stack"])) == (cur["fn"], cur["line"], len(cur["stack"])):
                    cur["returned"] = prev["returned"] + cur["returned"]
                    steps.pop(-2)
            returns, last_fn = [], fn
            state = d.command("step", load)
        if guard >= limit:
            print(f"{sc['id']}: stopped at max_steps={limit}", file=sys.stderr)
    finally:
        d.close()

    funcs, decls = parse_go(sorted(paths))
    drop_unassigned(steps, decls)
    # Each step shows its whole function.
    src, lines = {}, {}
    for st in steps:
        path = st.pop("path")
        rel = os.path.relpath(path, tree)
        first, last = next(((a, b) for a, b in funcs[path] if a <= st["line"] <= b), (st["line"], st["line"]))
        if path not in lines:
            with open(path) as f:
                lines[path] = f.read().split("\n")
        src.setdefault(rel, {}).update({str(n): lines[path][n - 1] for n in range(first, last + 1)})
        st["file"], st["range"] = rel, [first, last]
    src = {f: dict(sorted(ls.items(), key=lambda kv: int(kv[0]))) for f, ls in sorted(src.items())}
    normalize(steps)
    if not steps:
        print(f"{sc['id']}: no steps. The entry was not reached: check run and entry.\n"
              "Last output of the test:\n  " + "\n  ".join(d.out), file=sys.stderr)
    return {"go": go_version(tree, env), "steps": steps, "src": src}


def first_diff(a, b):
    """Where two traces of one scenario part, or None when they are the same."""
    if a == b:
        return None
    for i, (x, y) in enumerate(zip(a["steps"], b["steps"])):
        if x == y:
            continue
        what = [k for k in ("file", "line", "fn", "stack", "returned") if x[k] != y[k]]
        for k in ("args", "locals"):
            vx, vy = dict(map(tuple, x[k])), dict(map(tuple, y[k]))
            names = sorted(n for n in set(vx) | set(vy) if vx.get(n) != vy.get(n))
            if names:
                what.append(f"{k} {', '.join(names)}")
        where = f"{x['file']}:{x['line']}"
        if (x["file"], x["line"]) != (y["file"], y["line"]):
            where += f" vs {y['file']}:{y['line']}"
        return f"step {i + 1}, {where}: {'; '.join(what)}"
    if len(a["steps"]) != len(b["steps"]):
        return f"the end: {len(a['steps'])} steps vs {len(b['steps'])}"
    return "the Go version" if a["go"] != b["go"] else "the source shown"


def dlv_version(dlv):
    try:
        out = subprocess.run([dlv, "version"], capture_output=True, text=True).stdout
    except OSError as e:
        sys.exit(f"cannot run dlv ({dlv}): {e}")
    m = re.search(r"Version:\s*(\S+)", out)
    return m.group(1) if m else "unknown"


def main():
    args = sys.argv[1:]
    check = "--check" in args
    args = [a for a in args if a != "--check"]
    if not args:
        sys.exit(__doc__)
    cfg_path = os.path.abspath(args[0])
    only = args[1:]
    base = os.path.dirname(cfg_path)
    with open(cfg_path) as f:
        cfg = json.load(f)
    dlv = cfg.get("dlv") or os.environ.get("DLV") or "dlv"
    cfg["dlv"] = os.path.join(base, dlv) if "/" in dlv else dlv
    trees = {k: os.path.join(base, v["path"] if isinstance(v, dict) else v)
             for k, v in cfg["trees"].items()}
    out = os.path.join(base, cfg.get("traces", "traces.json"))
    old = {}
    if only and os.path.exists(out):
        with open(out) as f:
            old = {t["id"]: t for t in json.load(f)["scenarios"]}
    unknown = set(only) - {sc["id"] for sc in cfg["scenarios"]}
    if unknown:
        sys.exit(f"unknown scenario: {', '.join(sorted(unknown))}")
    meta = {"dlv": dlv_version(cfg["dlv"]), "test_flags": TEST_FLAGS}
    res, failed = [], False
    for sc in cfg["scenarios"]:
        if only and sc["id"] not in only:
            if sc["id"] in old:
                res.append(old[sc["id"]])
            continue
        tree = trees[sc.get("tree", "default")]
        t0 = time.time()
        tr = trace(cfg, tree, sc)
        msg = f"{sc['id']}: {len(tr['steps'])} steps in {time.time() - t0:.0f}s"
        if check and tr["steps"]:
            diff = first_diff(tr, trace(cfg, tree, sc))
            msg += "; a second run gave the same trace" if diff is None else f"; a second run differs at {diff}"
            failed |= diff is not None
        failed |= not tr["steps"]
        print(msg, file=sys.stderr)
        about = {k: sc.get(k, "") for k in ("id", "group", "title", "summary", "note")}
        run = {"tree": sc.get("tree", "default"), "before": sc.get("before", False), "pkg": sc["pkg"],
               "run": sc["run"], "entry": sc["entry"], "env": run_env(cfg, sc),
               "build_flags": build_flags(cfg, sc)}
        res.append(about | run | tr)
    with open(out, "w") as f:
        json.dump({"meta": meta, "scenarios": res}, f, indent=1)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
