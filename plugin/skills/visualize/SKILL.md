---
name: visualize
description: >
  This skill should be used when the user or agent needs to "visualize code",
  "show the architecture", "generate a diagram", "draw the flow", "map dependencies",
  "show relationships", or when understanding of structure, flow, or relationships
  would benefit from a visual representation. Reads code, artifacts, or descriptions
  and auto-generates a self-contained HTML diagram that opens in any browser.
user-invocable: true
---

# Visualize

Read code or artifacts, auto-generate diagrams. **The output is one self-contained
HTML file:** inline css, inline svg, every asset the page needs carried inside it.
It opens in any browser, on any machine, offline.

That portability is the property to protect. When someone asks for a different
format, hand them the HTML and say what it contains.

## Procedure

1. **Read** the source: code, a spec, or the user's description.
2. **Pick the zoom.** Overview unless asked otherwise.
3. **Pick the type** from the table below.
4. **Draw it.** CSS boxes or inline `<svg>`, from the skeletons in `references/`.
   Start minimal. If it feels too tangled to place by hand, that is the zoom level
   talking: raise it, or split into several focused diagrams.
5. **Check it is self-contained.** This should come back empty:

   ```
   grep -nE 'https?:|src=|<link|@import|cdn|url\([^#]' diagram.html
   ```

   Internal SVG fragment references (`url(#arrow)`) are fine and already excluded.
6. **Give the path once** and say to keep the tab open, then expect 2-3 rounds.
   Diagrams are visual: the user has to see it before they can say what is wrong.
   Rewrite that same path each round, never a new name, or the open tab goes stale
   pointing at the old file. On "too many arrows", remove the least important ones
   rather than stripping them all.

## Zoom Levels

**Overview** is the default and the big picture: components as labeled boxes,
arrows for relationships, 5-8 nodes, plain-English labels, edges naming what flows.
A non-programmer could read it. No signatures, paths, or line numbers.

**Detail** is the engineering view, on request ("zoom in", "show functions", "the
internals of X"): function names and signatures, types on the edges, decision
branches, and `file:line` so a reader can navigate. 10-20 nodes.

## Diagram Types

| # | Type | Shows | Asked as |
|---|------|-------|----------|
| 1 | Architecture / Component | how the system is structured: parts, roles, connections | "how is this structured", "visualize this repo" |
| 2 | Flow / Pipeline | how execution moves from input to output | "how does this work", "draw the pipeline" |
| 3 | Dependency / Relationship | what depends on what: files, packages, entries | "what depends on what" |
| 4 | Interface / Type | type hierarchies, implementations, struct fields | "what implements this", "class diagram" |
| 5 | State / Decision | states, transitions, decision trees | "show the gates", "state machine" |

## Visual Design Rules

- **Start minimal.** Labeled rectangles, labeled arrows, nothing else. Add
  descriptions, legends, and color coding only when asked.
- **Type sizes.** Node labels 14-16px, edge labels 12-13px. Nothing below 12px:
  make the node bigger or the text shorter instead.
- **Arrows are the main source of clutter.** One per relationship, and drop any
  that carries no information. More than two feedback loops means the diagram is
  too detailed for its zoom level.

### Colors - Default palette

Dark by default. The skeletons declare these tokens; style against them so a
change is one edit:

```css
:root{
  --bg:#1e1f29; --node:#282a36; --line:#6272a4; --ink:#f8f8f2;
  --arrow:#8895b3; --muted:#b0b8d1; --accent:#bd93f9;
}
```

If the user asks for something else, swap the values and keep the names.

## Live Updates

The skeleton ends with a LIVE RELOAD block. The page reloads itself every 2s, so a
tab left open picks up each rewrite on its own. Keep it while you iterate. Delete it
before the file goes to anyone else, or it reloads forever on their machine too.

A `file://` page cannot `fetch()` its own source, so the block reloads the whole
page rather than reading the file. It pauses while the tab is hidden and keeps the
scroll position, so a long diagram does not jump back to the top.

## Skeletons

`references/skeleton.html` is one complete page carrying both ways to draw. Copy
it, keep block A or block B, delete the other in the `<style>` and the `<body>`,
then replace the diagram.

| | use it for | why |
|---|-----------|-----|
| **A** CSS boxes | sequences, shallow trees | text selects and reflows; the row becomes a column on a narrow screen |
| **B** inline SVG | edges that cross, branch, loop, or skip nodes | you place everything, so you can draw anything |

The two mistakes that cost the most time are commented in the file at the point
they matter: the CSS edge label has to stay in flow or a long label overruns the
next node, and the SVG arrowhead has to be styled by class because `var()` does
not resolve in a presentation attribute.
