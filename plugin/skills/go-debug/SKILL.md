---
name: go-debug
description: >
  This skill should be used when the user wants to step through a Go change
  line by line with real values: "debug step by step", "step through the
  code", "see what each line does to the data", "walk through the diff in the
  debugger", or runs "/go-debug". Runs the Go tests that reach the change under
  Delve, records every line with the values of its variables, and builds one
  HTML page to step through them.
user-invocable: true
argument-hint: "[-r <rev>] [--from <rev>] [<functions or tests to step through>]"
---

# Go Debug

Run the Go tests that reach a change under Delve, record each line they run
with the real values of the variables, and build one HTML page to step through
it. For each step the page shows:

- the code, with the line that runs next, the line that just ran, and `+` on
  lines the change adds;
- what the last step did to the data: `cf.AuthConfigs gained key "..."`,
  `c.Items appended Item{Name: "apple", Price: 3}`, `c.Total: 0 → 3`, calls and
  what they returned;
- a plain note on the line, which you write;
- every argument and local, with new and changed ones tagged.

A before scenario runs the same test on a copy without the fix, so the user
sees the bug next to the fix.

You choose what to step through: you read the diff and judge which code
matters. The scripts only record and draw. `X` below stands for this skill's
`scripts/` directory.

## Arguments

`/go-debug [-r <rev>] [--from <rev>] [<functions or tests>]`

- No arguments: the current diff of the repo around the cwd. jj takes `@`, or
  `@-` when `@` is empty; git takes the uncommitted changes, or `HEAD` when
  there are none.
- `-r <rev>`: one revision. `--from <rev>`: the base to diff against, such as
  `--from main` for a whole branch.
- Anything else names what the user wants to step through: functions
  (`runLogs`, `k8s.PodSelector`) or tests (`TestLogs_Sidecar`). Use those, and
  add your own picks only to reach them.

## 1. Check the tools

```
command -v go && { [ -x "$DLV" ] || command -v dlv; }
```

If dlv is missing, install it into the scratchpad, from outside any Go module:

```
GOBIN=<scratchpad>/bin GOTOOLCHAIN=local go install github.com/go-delve/delve/cmd/dlv@v1.27.2
```

then set `DLV=<scratchpad>/bin/dlv`. Ask before you install it anywhere else.
The version is pinned so every run records with the same Delve. Delve refuses
a Go newer than it knows: when it says the Go version is too recent, raise the
pin here to a Delve release that supports it.

## 2. Read the change

- jj: `jj diff -r <rev> --git`, or `jj diff --from <base> --to <rev> --git`.
  Run jj without `--ignore-working-copy`, so `@` holds unsaved edits.
- git: `git diff` plus untracked files for uncommitted changes, or
  `git diff <base> <rev>`.
- The commit ids to export: `jj log -r <rev> --no-graph -T commit_id`, or
  `git rev-parse <rev>`. For git uncommitted changes, head is `WORKTREE`.

If the diff changes no Go code, say so in one line and stop.

## 3. Pick what to step through

A scenario is one test run (`go test -run`) and the functions to stop in
(`entry`). This is your judgment, unless the user named functions or tests.

- Read the diff whole. Find the functions it changes, and the tests that
  reach them: the tests the diff adds first, else grep for callers and their
  tests.
- Pick 2 to 5 scenarios: the case the change fixes, an edge case, and a case
  where the new code does nothing. Use one subtest each.
- Give the key ones a before scenario: the same test on a copy without the fix.
- Start at a caller one or two levels above the changed functions, so the page
  shows where the data comes from.
- When no test reaches a changed function, tell the user: that is a test gap.
  For the trace you may add a test to the exported copy, never to their repo.
- Tell the user in a short list which scenarios and entry functions you
  picked, so they can ask for others.

Delve names a function by its import path: `knative.dev/func/pkg/k8s.PodSelector`,
`<path>.T.M` for a method on a value, `<path>.(*T).M` on a pointer.
`go run $X/funcs.go -- <file.go>` lists a file's functions with their lines and
these names, without the import path.

## 4. Export the trees

Make a work dir outside the repo: `<scratchpad>/go-debug/<name>/`, or one the
user names. Never trace in the user's checkout: `dlv test` builds there, Go may
write go.sum, and the before edits must not touch the user's files.

```
$X/export-tree.sh <repo> <head> <work>/trees/head
$X/export-tree.sh <repo> <base> <work>/trees/base     # for the + marks
$X/export-tree.sh <repo> <head> <work>/trees/nofix    # then undo the fix in it
```

For a before tree, undo only the fix in a copy of head with Edit (delete the
one call, put back the old check), so the test and the rest stay the same. Say
in the scenario's `note` what you changed.

## 5. Write stepper.json

Put it in the work dir. Paths in it are relative to it. A full example, from
the knative/func PR this skill came from, is in `references/example/`.

| Field | Meaning |
| --- | --- |
| `title`, `revision` | Page heading, and the revision named under it. |
| `trees` | Name to `{"path": dir, "base": dir}`. `base` is optional and gives the `+` marks. A scenario picks a tree with `tree`, default `"default"`. |
| `dlv` | A name on PATH, or a path. Default: `$DLV`, then `dlv`. |
| `env` | Env for the build and the test, such as `{"GOTOOLCHAIN": "go1.26.10"}` when the project pins its Go. |
| `build_flags` | Passed to `dlv --build-flags`, such as `"-tags=integration"`. |
| `skip_types` | Types of variables to leave out, matched as substrings. `context.Context` and `net/http.RoundTripper` always are. Add big fakes the test passes everywhere, such as a fake clientset (`CoreV1Interface`): recorded at every step, they make the page tens of MB. |
| `notes`, `renderers` | Paths to notes.json and renderers.js (steps 7 and 9). |
| `out` | Page name, default `stepper.html`. |
| `max_steps`, `load` | Step limit (default 3000) and Delve load limits. |

Each scenario:

| Field | Meaning |
| --- | --- |
| `id` | Short and unique. The page URL uses it. |
| `group`, `title` | Tab group heading (such as the PR) and tab label. |
| `summary` | What the case is, in one or two sentences. |
| `note` | Shown in amber. For before scenarios, what the copy changes. |
| `before` | `true` draws the tab dashed. |
| `pkg`, `run` | Package dir for `dlv test`, and the `-test.run` pattern. |
| `entry` | Functions to stop in, under Delve's names. |
| `ours` | Name prefixes to step into. Default: the packages of `entry`. |
| `skip` | Functions of ours to step over, such as error helpers. |
| `include_tests` | `true` steps into `_test.go` code too. |
| `env`, `build_flags` | Override the top-level ones for this scenario. |

## 6. Trace

```
python3 -I $X/trace.py <work>/stepper.json --check [id ...]
```

It prints the steps per scenario. Zero steps means the entry was never
reached: check `run` and `entry`. The script then prints the end of the test's
output.

The run is made as repeatable as Go allows: the test runs with
`-test.count=1 -test.parallel=1 -test.shuffle=off` and `GOMAXPROCS=1` (set
`GOMAXPROCS` in `env` to change it), map entries are sorted by key, memory
addresses become labels (`#1`, `#2`), and the Go and Delve versions and the
settings go into `traces.json`. The same code then gives the same trace.

`--check` traces each scenario twice. "a second run gave the same trace" means
the trace is repeatable. Otherwise it names the first step where the runs part
and what differs there. That is the code's own doing: a `range` over a map,
time, randomness, a temp dir name or goroutine timing. Say so in the
scenario's `note`, or pick a test that avoids it.

`traces.json` is the record: each scenario's settings, then every step with
its line, stack, arguments, locals and returned values. Answer questions about
the run from it ("what did `cf` hold when line 120 ran?") without tracing again.

## 7. Write notes.json

A JSON object keyed by the trimmed text of a line. Use the key
`"<func>: <text>"` for a line that means different things in different
functions, with the function as the page's legend shows it, such as
`"canonicalizeDockerHubAuth: return"`.

Write a note for every line the diff adds, and for every line whose effect the
values alone do not show: two names for one map, a missing map key that reads
as a zero value, a sort that fixes the order. Say what the line does to the
data, in plain words. Skip what the step list already says.

## 8. Render

```
python3 -I $X/render.py <work>/stepper.json
```

It prints, per scenario, how many of the changed lines the trace ran, such as
`pkg/knative/deployer.go 19/28`. It counts only lines inside the functions the
trace shows. A scenario that runs none of the changed lines shows nothing about
the change: pick another test.

Give the user the page path once. The open tab reloads itself each time
render.py writes. Run trace.py again after code or test changes, and render.py
alone after note or view changes.

## 9. Custom views (optional)

The page shows structs, maps, lists and pointers on its own. When a domain type
reads badly that way, add a view in renderers.js:

```js
(() => {
  RENDERERS['types.AuthConfig'] = {
    leaf: true,                          // report a change as old -> new, not field by field
    full: (v, h, depth, prev) => '...',  // HTML for the variables pane
    short: (v, h) => '...',              // text for one-line summaries
  };
})();
```

The key is the Go type without its import path or a leading `*`. `h` holds
`esc`, `field(v, name)`, `str(v)`, `render`, `renderMap`, `fmt1` and
`shortType`. Keep the code inside the block, so its names do not clash with
the page's. `references/example/renderers.js` has working views.

## Sharing

- The values come from the test process's memory. Check that the tests use
  fake data before the page leaves the machine.
- `render.py <stepper.json> --share <file>` writes a copy without the reload
  code.
- Only when the user asks: `gh gist create <file>` makes a secret gist, but
  anyone with the link can read it. GitHub shows gist HTML as source; the page
  renders at `https://gist.githack.com/<user>/<id>/raw/<file>`.

## How the trace moves, and what it misses

- It steps into functions of ours and out of all others. A function of ours
  that other code calls back (an interface method such as a keychain's
  Resolve, a callback, a handler) is reached only through a breakpoint: list
  it in `entry` too.
- It records one call: the trace ends when no frame of ours is left on the
  stack. Pick a subtest that makes the call you want first.
- It follows one goroutine. Work on other goroutines does not show.
- Go turns spaces in subtest names into `_`. Escape regex characters:
  `^TestX$/^name_with\.dots$`.
- Values are cut: strings at 400 characters, lists at 64 items, 4 levels deep.
  Raise them with `load`. A map with more entries than that shows only its
  size: Delve would load another part of it on every run.
- A local shows only once it holds a value. Before that it holds whatever was
  in memory. So a function's first stop shows its arguments only, a local
  waits until the statement that declares it has run, and a range loop's key
  and value never show on the loop's head or first body line, because Go
  copies them in there on each pass.
- Wrappers the compiler writes (`<autogenerated>`) are stepped through
  without a step of their own.
- `▷` marks a stop part way through a line: a call on it returned, and the
  rest of the line, such as the assignment, runs next.
