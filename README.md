# ai

A cross-project Claude Code skills plugin for gauron's workflows.

- **`plugin/`** is a Claude Code plugin, `gauron`, published through the
  `gauron99` marketplace (install id `gauron@gauron99`). It ships 4 skills
  (see below).

## Prerequisites

- [Claude Code](https://docs.claude.com/en/docs/claude-code).
- Individual skills expect the tools they drive on your `PATH`, commonly
  [`jj`](https://github.com/jj-vcs/jj) and [`gh`](https://cli.github.com/).
  `func-test-cluster` expects a checkout of
  [Knative `func`](https://github.com/knative/func), `go` and Docker. `go-debug` expects
  `go`, `python3` and `dlv` (it installs a pinned `dlv` into a scratch dir if
  missing).

## Install the plugin

From inside Claude Code:

```
/plugin marketplace add gauron99/ai
/plugin install gauron@gauron99
```

The first command registers the `gauron99` marketplace from this repo; the
second enables the `gauron` plugin and makes all skills below available. You can
also run `/plugin` on its own for an interactive menu to browse and manage
marketplaces and plugins.

## Skills

| Skill | What it does |
| --- | --- |
| `pr-review` | Deep structured PR review: flow tracing, AI-slop detection, test adequacy. |
| `go-debug` | Run the Go tests that reach a change under Delve and step through what each line does to the data, in one HTML page. |
| `visualize` | Auto-generate a self-contained HTML diagram of code, flow, or relationships. |
| `func-test-cluster` | Create a local test cluster for Knative `func` with `func cluster create`, and run `make test-full` or one of its cluster test jobs on it. |

## Adding a skill

Create `plugin/skills/<name>/SKILL.md` with YAML frontmatter (`name`,
`description`) and the skill body.

## License

MIT, see [`LICENSE`](LICENSE).
