---
name: pr-review
description: Deep structured PR review - flow tracing, AI-slop detection, test adequacy. Catches PRs that look good but do nothing.
user-invocable: true
---

# PR Review

Structured deep review of a pull request. Traces function flows, detects AI-generated slop, verifies tests cover real behavior - not lines.

## Input

User provides one of:
- A PR URL (e.g. `https://github.com/owner/repo/pull/123`)
- A PR number (e.g. `#123` or `123`) - resolved against current repo

## Tools

- Use `jj` if the repo uses it; fall back to `git`
- Use `gh` subcommands (`pr`, `issue`, `run`) instead of `gh api` unless necessary
- Use codebase search (grep, find, LSP) to trace callers and references
- Use websearch when you need context on libraries, APIs, or patterns you don't recognize

## Behavior

- Do NOT assume knowledge - research the codebase and docs (websearch if necessary)
- Do NOT rely on model training - research and validate
- Do NOT flatter, sugar-coat, or bloat sentences in output
- State findings directly with evidence. No hedging, no "consider maybe perhaps."

## Steps

### Step 0: Repo familiarization (first run only)

If you have NOT already reviewed this repo's conventions in this session:
1. Read these files if they exist at the repo root: `AGENTS.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`, `CLAUDE.md`, `README.md`
2. Run `find . -maxdepth 2 -name '*.md' -not -path './.git/*' -not -path './.jj/*'` to locate other documentation
3. Identify: language, build system, test framework, naming conventions, directory layout
4. Hold this context for all subsequent reviews in this session - do not re-read on every invocation

### Step 1: Fetch PR and classify

1. Parse the PR reference. If a URL, extract `owner/repo` and PR number.
2. Fetch PR metadata:
   ```
   gh pr view <number> --json baseRefName,headRefName,title,body,author,files,additions,deletions,commits,url [-R <owner/repo>]
   ```
3. **Repo match - hard stop on mismatch:**
   - Determine the local repo: `jj git remote list` or `git remote get-url origin`
   - Compare against the PR's `owner/repo`
   - Match if: exact match, or one is a fork of the other (same repo name, upstream relationship)
   - On mismatch: **STOP.** Tell the user: "This PR belongs to `<pr-repo>` but I am in `<local-repo>`. Run me in the correct repo, or tell me where the checkout is." Do not proceed.
4. Fetch the full diff: `gh pr diff <number>`
5. List changed files: `gh pr view <number> --json files --jq '.files[].path'`
6. For each file, note: new / modified / deleted? Code / test / config / docs?
7. Classify the PR: feature, bugfix, refactor, test-only, config/infra, documentation

### Step 2: Read the discussion and CI

Read what reviewers, bots and CI already said before you judge the code. A point
someone already raised is not a new finding, and a red check is evidence.

1. Comments, reviews, CI status and linked issues:
   ```
   gh pr view <number> --json comments,reviews,reviewDecision,statusCheckRollup,closingIssuesReferences [-R <owner/repo>]
   ```
2. Comments on code lines are not in `gh pr view`. Fetch them:
   ```
   gh api repos/<owner>/<repo>/pulls/<number>/comments --paginate
   ```
3. Read each issue in `closingIssuesReferences` (`gh issue view <n>`). It says
   what the PR must fix; check the PR against it.
4. CI: `gh pr checks <number> --json name,state,bucket,link,workflow`. For each
   failing check, read the log: `gh run view <run-id> --log-failed` (the run id
   is in the check's `link`). Decide whether the PR caused it, or it is flaky or
   unrelated: see whether the same workflow fails on the base branch too
   (`gh run list --branch <base> --workflow <workflow> --limit 5`).
5. For each comment thread, note who raised what, whether the author answered
   or changed the code, and whether the point still holds at the PR's head.
   Check the code, not the thread's state: a resolved thread can still be wrong,
   and an open one may be fixed already.

### Step 3: Read changed files in full

For every file touched by the PR - not just the diff hunks:
1. Read the FULL current version of each modified and new file
2. For deleted files, note what they contained and what depends on them
3. Diff-only review misses how changes interact with surrounding code. Read the whole file.

### Step 4: Trace impacted function flows

For each non-trivial changed function or method:

1. **Callers**: Where is this function called from? Grep / LSP to find all call sites.
2. **Data flow**: What enters, how is it transformed, what exits?
3. **Control flow**: What branches? What error paths? What happens on nil / empty / invalid input?
4. **Side effects**: Disk writes, network calls, global state mutation, event emission?
5. **Exit conditions**: How does the function terminate? Are all paths accounted for?

Document each flow:
```
FLOW: <function_name> (<file>:<line>)
  Called by: <caller1>, <caller2>, ...
  Input: <parameters and their types/constraints>
  Transforms: <what the function does to the data>
  Output: <return values and side effects>
  Edge cases: <nil, empty, concurrent access, overflow>
  Error paths: <what happens when things fail>
```

If a function is new but has zero callers - flag it immediately. Dead code on arrival.

### Step 5: AI slop detection

Run each check explicitly. For each, state **PASS** or **FAIL** with evidence.

**5a. Hollow tests**
- Do assertions verify real behavior, or do they assert on constants / mocks / the test setup itself?
- Could you replace the implementation with `return nil` and tests still pass?
- Are tests testing the mock framework rather than the code? ("verify mock was called" without checking the result)
- `assert(result != nil)` on a function that never returns nil is not a test.
- Does the test exercise a real code path, or just construct an object and check its fields?

**5b. Phantom functionality**
- Does the PR description claim a behavior change? Trace the code - is the claim real?
- Are new functions actually called from somewhere, or are they dead code?
- Are return values from new/changed functions used by callers, or silently dropped?
- Does the PR add a capability that nothing invokes?

**5c. Cosmetic disguised as functional**
- Is this "refactor" just renaming without behavior change?
- Are imports reorganized, comments reworded, formatting changed - presented as meaningful?
- Does moving code between files change how it executes?

**5d. Error swallowing**
- Errors caught and silently discarded? (`_ = someFunc()`, empty catch blocks, `if err != nil { return nil }`)
- Generic meaningless error messages? ("an error occurred", "something went wrong")
- Error context lost in wrapping? (Go: wrapping without `%w`. Java: catching and rethrowing without cause)

**5e. Cargo-cult patterns**
- Boilerplate copied from elsewhere that doesn't apply here?
- Design patterns where a simple function would suffice?
- Abstractions with exactly one implementation and no realistic prospect of a second?
- Interfaces defined for types used in exactly one place?

**5f. Description mismatch**
- Does the PR title/body accurately describe what the code does?
- Could this description apply to any PR? ("Improve code quality", "Refactor for clarity", "Update implementation")
- Claims in the description not supported by the diff?

### Step 6: Test adequacy

For each piece of new or changed functionality:

1. **Does a test exist?** If not, flag it.
2. **What kind of test is needed?**
   - New architecturally complex feature with user-facing behavior → e2e test
   - New integration between components → integration test
   - Pure logic / computation → unit test
   - Bug fix → regression test (must fail without the fix, pass with it)
3. **Does the test actually cover the change?** Trace from test setup through assertion - does it hit the changed code path?
4. **Test quality:**
   - Does the test name describe the scenario, not the implementation?
   - Clear arrange / act / assert structure?
   - Would the test fail if the implementation were wrong? (mental mutation testing)
   - Edge cases: empty input, nil, boundary values, error conditions?

We do NOT care about line coverage. We care about functionality coverage. A feature without a test that proves it works is incomplete.

### Step 7: Produce the review

Output a structured review:

```
## Summary
One paragraph: what this PR actually does (based on code, not the description).

## Repo
CONFIRMED: <owner/repo> matches local checkout.

## Classification
Type: feature | bugfix | refactor | test | config | docs
Risk: low | medium | high
Size: S (<50 lines) | M (50-200) | L (200-500) | XL (500+)

## Discussion and CI
- Reviews: <reviewDecision; who approved, who asked for changes>
- Still open: <each point from others that still holds at head: author, file:line, one line> (or: none)
- Settled: <points the author fixed or answered well> (or: none)
- CI: <all green | each failing check: caused by the PR, flaky or unrelated, with the evidence>

## Flow analysis
[FLOW blocks from Step 4]

## Findings

### Critical (blocks merge)
- [C1] <file>:<line> - <issue>. <why it matters>. <fix>.

### Significant (should fix before merge)
- [S1] <file>:<line> - <issue>. <why it matters>. <fix>.

### Minor (fix or justify)
- [M1] <file>:<line> - <issue>.

### AI slop
- [SLOP-1] <check that failed> - <evidence>.
(or: No AI slop detected.)

## Test assessment
- Covered: <what is tested>
- Missing: <what needs tests, with suggested scenarios>
- Quality: <are existing tests real or hollow>

## Verdict
APPROVE | REQUEST CHANGES | NEEDS DISCUSSION
<one-line justification>
```

Do NOT post this as a PR comment automatically. Output it for the user to review first. Ask the user what to do (post as-is, adjust, or discard).

## Rules

- NEVER skip the repo match check. A review of the wrong repo is worse than no review.
- NEVER review only the diff. Read changed files in full to understand context.
- NEVER take the PR description at face value. Verify every claim against the code.
- Read callers, not just the changed function. A function nobody calls is dead code no matter how clean it looks.
- If you lack domain knowledge to judge correctness, say so. Do not guess.
- Do not comment on style preferences unless they violate the repo's documented conventions.
- Tests are code. Run the same slop checks on test files that you run on production code.
- Findings MUST cite specific file and line. No vague "consider improving error handling."
- When unsure about severity, include the finding as Minor rather than suppressing it.
- Empty findings sections are fine. Do not invent issues to fill the template.
- Do not pass off a point someone already raised as your own. Put it under "Still open", or in Findings marked "(raised by <author>)" when you add evidence or a fix. Write the author's name without "@", so a posted review pings no one.
- A failing CI check is a finding unless you show it is flaky or unrelated to the PR.
- A PR that does nothing useful does not merge, no matter how clean it looks.
