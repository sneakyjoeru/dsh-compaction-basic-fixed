# dsh-compaction-basic-fixed

Compaction (condensation) backend for the **DeepSeek Harness (dsh)** web — a fixed copy of the
shipped `@deepseek-ai/dsh-compaction-basic` **0.2.1-rc.2**, re-defaulted so **compaction starts at
exactly 80% of the context window** with zero extra headroom, and carrying three long-session fixes
from live operation.

[Русский — описание и установка](README.ru.md)

## What it does

As token pressure builds, dsh compaction condenses the oldest history into one structured summary
message, keeps the recent tail verbatim, and retries the request after a confirmed context-overflow
error. With `dsh-command-compact` mounted, `/compact` condenses on demand; with
`dsh-compaction-tool-result-pruner` mounted, oversized tool outputs are trimmed first (no model
call needed when the trim alone suffices).

### Defaults in this package — "compact at 80%"

| Setting | Default here | Shipped default |
|---|---|---|
| `thresholdRatio` | `0.8` | `0.8` |
| `headroomTokens` | `0` | `65536` |
| `retainRatio` | `0.2` | `0.16` |
| `maxTokens` | `4096` | follows headroom (`65536`) |

Trigger = `floor(min(0.8 · W, W − O))` where `W` is the routed model's context window and `O` the
request output cap. The shipped 65,536-token headroom makes the effective trigger land far below
80% on large windows (≈47% on a 131k window); with headroom `0` the trigger lands exactly at
80% and the worst-case request size is `0.8·W + O`.

All settings remain overridable (globally or per route via `modelPolicies`); every field works
unchanged here — only the defaults moved.

## Local fixes (marked `LOCAL OVERRIDE` in `lib/index.js`)

1. **Retained-tail walk** — the shipped walk priced the retained tail with *routed* tokens only.
   With sparse routed attribution (tool results, splices, images) the compactable span collapsed to
   a sliver and the size guard rejected every attempt. This copy takes the larger of routed and
   heuristic tokens per node.
2. **Dense-content fallback** — the meter's chars-per-token heuristic underprices dense tool
   output, so the `retainTokens` walk could consume the *entire* surface and return no range until
   the real prompt overflowed. This copy keeps the last two surface nodes verbatim (retreating to a
   balanced tool boundary) so a threshold crossing always yields a compactable range.
3. **Size guard** — the shipped guard compared the framed summary's *estimated* size against the
   shadowed span's *routed* size; in long sessions the routed count collapses and the guard
   rejected everything (measured: 93 wasted attempts in 59 minutes). This copy compares against the
   larger of the two measures.

## Install

### Desktop (native dsh install)

1. Clone into dsh's plugins directory (`$DSH_HOME` is dsh's home dir — check `dsh --help`;
   typically `~/.dsh`):

   ```sh
   git clone https://github.com/sneakyjoeru/dsh-compaction-basic-fixed \
     "$DSH_HOME/plugins/dsh-compaction-basic"
   ```

2. Mount it in the user-profile config
   `$DSH_HOME/profiles/<profile>/cordis.patch.yml` — replace the shipped `compaction-basic`
   entry with a file-URL mount (**absolute path required**):

   ```yaml
   - id: compaction-basic
     name: /absolute/path/to/plugins/dsh-compaction-basic/lib/index.js
   ```

   On the stock `standard` preset the entry lives in the preset's `compaction` group (preset plane);
   mounting it in the host plane alone is dead config there.

3. Restart dsh. In the boot log there must be **no** `entries did not activate` line for the
   compaction entry.

### Remote server (dsh in a Docker container, e.g. a NAS)

1. Get the code inside the container's `$DSH_HOME` (on a UGREEN NAS stack
   `/volume1/docker/dsh`, that is `/volume1/docker/dsh/home` — `exec` into `dsh-web` or clone from
   a host that shares the volume):

   ```sh
   git clone https://github.com/sneakyjoeru/dsh-compaction-basic-fixed \
     "$DSH_HOME/plugins/dsh-compaction-basic"
   ```

2. Add the same file-URL mount line to `$DSH_HOME/profiles/web/cordis.patch.yml`.
3. Recreate the container — do not hot-patch a running instance:

   ```sh
   docker compose up -d --force-recreate dsh-web   # or your dsh-upgrade.sh
   ```

   Active sessions drop on the recreate; reload the page once the log says `ONLINE`.
4. Verify: `docker logs dsh-web 2>&1 | grep -c "entries did not activate"` is `0`; the browser
   context meter reads 100% at the 80%-of-window barrier and compaction fires there; `/compact`
   works.

### Alternative: package install

```sh
cd dsh-compaction-basic && npm pack
dsh plugin --profile web add file:$PWD/dsh-compaction-basic-0.2.1-rc.2.tgz
```

Then add the file-URL mount line above so the local copy (with the 80% defaults and the three
fixes) is the one actually mounted.

## Re-basing after a dsh upgrade

The package is pinned to the 0.2.1-rc.2 peer set (`@deepseek-ai/dsh-*` at that version). After each
dsh bump: diff this `lib/index.js` against the newly shipped `dsh-compaction-basic` and re-apply the
three `LOCAL OVERRIDE` hunks — the upstream file is otherwise the source of truth.

## License

MIT (copy of the shipped package, same terms).
