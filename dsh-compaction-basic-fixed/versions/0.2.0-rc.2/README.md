# dsh-compaction-basic-fixed — local override (2026-10-12)

A byte copy of the shipped `@deepseek-ai/dsh-compaction-basic` (0.2.0-rc.2) with **three lines changed**
so long sessions stop re-summarising forever. Wired in by `profiles/web/cordis.patch.yml`:

```yaml
- id: compaction-basic
  name: '/volume1/docker/dsh/home/plugins/dsh-compaction-basic-fixed/lib/index.js'
```

`patches/sync-standard-preset-compaction.mjs` emits the same `name:` (override it with
`COMPACTION_PLUGIN_NAME=<module>` for a rollback).

## What was broken (measured 2026-10-12)

Both the retained-tail walk and the size guard price things with **routed** tokens
(`node.tokens`), which are sparse in agent sessions (tool results, inbox splices, images carry no
routed attribution):

* `selectCompactableRange` walked back until it had gathered `retainTokens` (~20% of the window) of
  routed tokens — with sparse attribution that is almost the whole conversation, so the compactable
  span collapsed to a sliver (~1.3k tokens measured).
* The guard then required the framed summary to be **strictly smaller** than that sliver's routed
  count. The summary merges the previous checkpoint, so it lands at ~the same size → `>=` → rejected
  → dsh retried on **every step**, burning a summarisation plus a full re-prefill each time
  (session-fdde1265: 93 attempts / 59 min, 13 installed; session-9d900141: 78 attempts, ~30 guard
  failures). No config knob touches either line, and upstream 0.2.0-rc.2 **and** 0.2.1-alpha.2 still
  carry the originals — verified by unpacking both published plugins.

## The patch

1. `selectCompactableRange`: `accumulated += Math.max(node.tokens ?? 0, node.heuristicTokens ?? 0)`
   — the retained tail is never smaller than the shipped rule, and the span becomes the real
   (estimated) remainder of the window.
2. `summarizeCompaction` guard:
   `const shadowedComparableTokenCount = Math.max(prepared.shadowedTokenCount, prepared.shadowedRouteTokenCount)`
   — the guard is never weaker than the shipped one, but the collapsed-routed case can no longer
   livelock it.

Both changes are marked `LOCAL OVERRIDE 2026-10-12 (not upstream)` in `lib/index.js`.

### 2026-10-20: third change — guarantee a compactable range

Dense content (digits, JSON, code) tokenizes far denser than the meter's chars-per-token
heuristic, so the `retainTokens` walk could accumulate the whole surface without reaching the
budget; `selectCompactableRange` then returned `null` on **every** step while the trigger kept
firing. The live prompt grew towards the window with nothing compacted:

* measured on qwen3.8 (160k window), headless 10-step session whose tool results were
  `seq 1 1500` (~6.5k real tokens each, priced ~1.5k by the heuristic):
  the threshold crossed at step 3 (129,367 real tokens) but no range was selectable until
  step 7 - by then the summarisation request had grown to **155,702 tokens**, 4.3k under the
  160k limit. One more step would have overflowed before compaction could run.
* on the 131k Strata engine the same overshoot would cross `--max-context` and 400.

`selectCompactableRange` now falls back to keeping the last two surface nodes verbatim
(retreating to a balanced tool boundary, and returning null only when even that is impossible)
when the walk would consume everything. Re-measured on the same task: compaction fired at
step 3, the summarisation request was 129,757 tokens (26,243 under 160k), and the turn
continued to step 11 with `DONE`.

## Maintenance

* `node_modules` is a **symlink** to the image's `@deepseek-ai/dsh/node_modules`, so the copy resolves
  its imports from any container; nothing is installed here.
* Verify after any image upgrade:
  `node --check lib/index.js && node -e "import('/volume1/docker/dsh/home/plugins/dsh-compaction-basic-fixed/lib/index.js').then(m=>console.log(Object.keys(m)))"`
  → must print `[ 'BasicCompactionEngine', 'default' ]`.
* **When upstream fixes the two lines** (check `lib/index.js:419` and `:608` semantics in a fresh
  image): delete the `name:` override from `cordis.patch.yml` (and `COMPACTION_PLUGIN_NAME` from the
  generator) and retire this directory. This copy freezes the plugin at 0.2.0-rc.2 and will **not**
  inherit upstream changes, so re-diff it against the image's copy after every dsh upgrade.
* Boot check after any change: the harness must NOT print "entries did not activate".
