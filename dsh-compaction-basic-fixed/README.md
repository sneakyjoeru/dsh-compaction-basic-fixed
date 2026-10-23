# dsh-compaction-basic-fixed

Compaction backend for the **DeepSeek Harness (dsh)** that (1) compacts at a **user-settable
percentage of the routed model's context window** (default **80%**, global or per model), (2) carries
three fixes for long sessions, and (3) **survives dsh upgrades**: a stable loader picks the copy that
matches the installed dsh, or falls back to the shipped package so compaction is never dead.

[Русский](README.ru.md)

## Layout

```
dsh-compaction-basic-fixed/
  index.mjs            <- the ONLY path the profile mounts (stable across dsh versions)
  package.json         <- engines.dsh ">=0.2.1-rc.2": dsh's preflight never disables the row
  verify.mjs           <- unit check: node verify.mjs -> ALL PASS
  versions/<dsh-compaction-basic version>/lib/index.js   <- re-based copies with the fixes
  node_modules -> /usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules   (symlink for bare imports)
../dsh-compaction-threshold/index.mjs                   <- the setting (see its README)
```

## How the loader decides

1. Read the installed `@deepseek-ai/dsh-compaction-basic` version.
2. `versions/<version>/lib/index.js` exists -> load it (long-session fixes active).
3. Otherwise -> load the **shipped** package and log a warning. Compaction keeps working with upstream
   behaviour (same config schema, the preset row stays valid); only the fixes pause until a copy is
   re-based. One line goes to stderr / `dsh-web.log` on every boot:
   `compaction-basic-fixed: fixed copy versions/0.2.1-rc.2 (long-session fixes active)` or
   `compaction-basic-fixed: SHIPPED ... long-session fixes INACTIVE, compaction itself works`.

In both cases the exported plugin is a subclass that overlays the live **compaction-threshold**
setting through a `config` accessor: `thresholdRatio` = global percentage / 100, each `perModel`
row becomes a `modelPolicies` override, and retention is clamped below a low trigger. No code inside
the copies is touched for this, so it survives upstream refactors as long as the engine reads
`this.config.{thresholdRatio,retainRatio,retainTokens,modelPolicies}` (its public config contract).

## The three long-session fixes (in `versions/*/lib/index.js`, marked `LOCAL OVERRIDE`)

1. **Retained-tail walk** priced the tail with routed tokens only; with sparse routed attribution the
   compactable span collapsed and every attempt was rejected. Now max(routed, heuristic) per node.
2. **Dense-content fallback**: the chars-per-token heuristic underprices dense tool output, so the
   `retainTokens` walk could consume the whole surface and return no range until the real prompt
   overflowed. Now the last two surface nodes are kept (retreating to a balanced tool boundary).
3. **Size guard** compared the summary's estimated size against the span's routed size and rejected
   everything in long sessions (93 wasted attempts in 59 min). Now against max(routed, heuristic).

## Install

### Desktop (native dsh)

```sh
git clone https://github.com/sneakyjoeru/dsh-compaction-basic-fixed "$DSH_HOME/plugins/dsh-compaction"
cd "$DSH_HOME/plugins/dsh-compaction/dsh-compaction-basic-fixed"
ln -sfn "$(dirname "$(dirname "$(node -p 'require.resolve("@deepseek-ai/dsh/package.json")')")")/dsh/node_modules" node_modules
node verify.mjs      # ALL PASS
```

`$DSH_HOME/profiles/<profile>/cordis.patch.yml` — the `compaction-basic` row lives in the agent
preset's `compaction` group (preset plane); a host-plane row is dead config on the stock `standard`
preset. Point it at the loader (absolute path):

```yaml
- id: compaction-basic
  name: /ABS/PATH/plugins/dsh-compaction/dsh-compaction-basic-fixed/index.mjs
  config: { thresholdRatio: 0.8, retainRatio: 0.2, headroomTokens: 0, maxTokens: 4096 }
```

Mount the setting too (host plane, see `../dsh-compaction-threshold/README.md`), then restart dsh.
Boot log must not say `entries did not activate`.

### Remote server (dsh in Docker, e.g. a NAS)

Same files inside the container's `$DSH_HOME` (persistent volume, so they survive image rebuilds);
the symlink target `/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules` is version-independent.
Recreate the container (`docker compose up -d --force-recreate dsh-web`), never hot-patch a running one.
Then: `docker logs dsh-web 2>&1 | grep compaction-basic-fixed:` shows which path is active.

### After a dsh upgrade (re-basing a copy)

```sh
V=$(node -p 'require("@deepseek-ai/dsh-compaction-basic/package.json").version')   # run inside node_modules
cp -a /usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-compaction-basic versions/$V
# re-apply the three LOCAL OVERRIDE hunks from the previous versions/*/lib/index.js (diff them side by side)
node verify.mjs
```

Until then the loader runs the shipped package — nothing blocks.

## License

MIT (copies of the shipped package keep its terms).
