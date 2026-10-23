# dsh compaction kit — compact at N% of the model's context window, upgrade-proof

Three pieces for the **DeepSeek Harness (dsh)** web, taken from a production NAS deployment:

| Piece | What it does |
|---|---|
| [`dsh-compaction-basic-fixed/`](dsh-compaction-basic-fixed/README.md) | Compaction backend. **Stable loader**: loads the re-based copy matching the installed `dsh-compaction-basic` (three long-session fixes), or falls back to the shipped package — compaction never goes dead after a dsh upgrade. Overlays the live threshold setting. |
| [`dsh-compaction-threshold/`](dsh-compaction-threshold/README.md) | The setting: *compact at **N %** of the routed model's context window* — default **80**, decimals allowed, global **and per provider/model**. Live, no restart. |
| [`patches/meter-compaction-percent.py`](patches/meter-compaction-percent.py) | Optional UI patch for the context-meter popup: text field `Compact at [ 80 ] %`, trigger shown in tokens for the routed model, checkbox `only for <model>`. Ring/percentage read 100 % at the trigger. Non-fatal on anchor drift. |

[Русский — установка](README.ru.md)

## Why

- Upstream `dsh-compaction-basic` reserves 65,536 headroom tokens by default, so on a 131k window it
  compacts at ~47 %, not 80 %. Here the trigger is `floor(min(ratio · W, W − O))` with ratio from the
  setting and `W` the window of the model that is **actually routed** — a percentage, never a token count.
- Long sessions tripped three upstream guards (routed-token-only tail walk, dense-content walk
  exhaustion, estimated-vs-routed size guard) and re-summarised on every step — fixed in the copies.
- A copy of a shipped package is pinned to one dsh version; dsh's preflight disabled the row after a
  bump (measured 2026-10-23). The loader removes that failure mode (`engines.dsh` open range + runtime
  version gate + shipped fallback + one provenance line in the log).

## Install — desktop (native dsh)

1. Clone next to your dsh home and link bare imports to dsh's own packages:

   ```sh
   git clone https://github.com/sneakyjoeru/dsh-compaction-basic-fixed "$DSH_HOME/plugins/dsh-compaction"
   cd "$DSH_HOME/plugins/dsh-compaction"
   DSH_NM="$(dirname "$(node -p 'require.resolve("@deepseek-ai/dsh/package.json")')")/node_modules"
   ln -sfn "$DSH_NM" dsh-compaction-basic-fixed/node_modules
   ln -sfn "$DSH_NM" dsh-compaction-threshold/node_modules
   node dsh-compaction-basic-fixed/verify.mjs      # ALL PASS
   ```

2. `$DSH_HOME/profiles/<profile>/cordis.patch.yml` (absolute paths):

   ```yaml
   # host plane — the setting
   - insert:
       - id: compaction-threshold
         name: /ABS/PATH/plugins/dsh-compaction/dsh-compaction-threshold/index.mjs
   # preset plane — inside your agent preset's `compaction` group (a host-plane
   # compaction-basic row is dead config on the stock `standard` preset)
   - id: compaction-basic
     name: /ABS/PATH/plugins/dsh-compaction/dsh-compaction-basic-fixed/index.mjs
     config: { thresholdRatio: 0.8, retainRatio: 0.2, headroomTokens: 0, maxTokens: 4096 }
   ```

3. Optional popup UI: `python3 patches/meter-compaction-percent.py` against the installed
   `dsh-client-ui-conversation/lib/client.js` (it locates it under `/usr/local/lib` by default).
   Re-run after every dsh upgrade; it skips with a loud line if upstream moved.
4. Restart dsh. Log must show `compaction-basic-fixed: fixed copy ...` and no `entries did not activate`.

## Install — remote server (dsh in Docker, e.g. a NAS)

1. Put the clone inside the container's `$DSH_HOME` (the persistent volume), symlink `node_modules`
   to `/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules` (same path in every image).
2. Same two mounts in `profiles/web/cordis.patch.yml`.
3. Apply the UI patch in your **Dockerfile** (`COPY patches/meter-compaction-percent.py /opt/nas-patches/`
   + `RUN python3 /opt/nas-patches/meter-compaction-percent.py`) so it survives rebuilds.
4. Recreate the container (`docker compose up -d --force-recreate dsh-web`); never hot-patch a running one.
5. Verify: `docker logs dsh-web 2>&1 | grep -E "compaction-basic-fixed:|did not activate"`, open a chat,
   click the context ring — the popup shows the editor.

## After a dsh upgrade

Nothing to do for compaction to keep working. To get the long-session fixes back on the new version:
copy the newly shipped `dsh-compaction-basic` into `dsh-compaction-basic-fixed/versions/<version>/`,
re-apply the three `LOCAL OVERRIDE` hunks, run `verify.mjs`, restart.

MIT. The `versions/*` copies keep the upstream package's MIT terms.
