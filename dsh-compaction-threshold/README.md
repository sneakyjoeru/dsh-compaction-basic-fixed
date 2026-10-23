# dsh-compaction-threshold

The user-editable compaction trigger for the **DeepSeek Harness (dsh)**: *compact when the next
request would reach **N %** of the routed model's context window*, globally and per exact
provider/model route. Default **80**. Decimals allowed (`75.2`). Range 1–100.

The value is a **ratio of the model's advertised window** — never a token count. Switch the session
to a model with another window and the trigger moves with it.

## What it is

One host-plane plugin (file-URL mount, no package install) with two `volatile` settings fields:

| Field | Default | Meaning |
|---|---|---|
| `thresholdPercent` | `80` | Trigger for every model without its own row. |
| `perModel[]` | `[]` | Rows `{ provider, model, thresholdPercent }`; an exact match wins over the global value. |

It exposes the service **`compactionThreshold`** (`resolve({provider, model})` →
`{ percent, ratio, source: "model" | "global" | "default" }`). The compaction loader
(`../dsh-compaction-basic-fixed/index.mjs`) reads it on every policy resolution via `ctx.get`, so
changes apply live, without a restart, to the next pressure check. Both sides are optional: without
the backend the setting is inert; without this plugin the backend keeps its configured ratio.

## Where it is edited

- **Context-meter popup** (click the ring/percentage under the composer) — with the image patch
  `patches/meter-compaction-percent.py` v2: a text field `Compact at [ 80 ] % of context`, the
  trigger in tokens for the model actually routed, and a checkbox `only for <model>` that stores a
  per-route row instead of the global value. Enter/blur saves, Escape reverts. The ring and the
  figures line follow the live value (100 % = the trigger).
- **Settings** — dsh auto-generates a form for every plugin with volatile fields; the namespace is the
  entry id `compaction-threshold`.
- **File** — `profiles/<profile>/cordis.patch.yml`, like every other setting dsh persists.

## Install

```yaml
# $DSH_HOME/profiles/<profile>/cordis.patch.yml  (host plane)
- insert:
    - id: compaction-threshold          # <- this id IS the settings namespace
      name: /ABS/PATH/plugins/dsh-compaction/dsh-compaction-threshold/index.mjs
```

Bare imports (`@deepseek-ai/cordis`, `@deepseek-ai/schemastery`) resolve through a `node_modules`
symlink next to the file (→ dsh's own `node_modules`); the clone's sibling
`dsh-compaction-basic-fixed/node_modules` symlink covers this directory too when both live under one
parent, otherwise create the same symlink here. Restart dsh (recreate the container on Docker).
`package.json` declares `engines.dsh: ">=0.2.1-rc.2"`, so dsh's compatibility preflight accepts it on
every later version.

Smoke test (no dsh boot needed):

```sh
node --input-type=module -e '
import { Context } from "@deepseek-ai/cordis";
import P from "./index.mjs";
const root = new Context(); root.plugin(P, { thresholdPercent: 70 });
await new Promise(r => setTimeout(r, 50));
console.log(root.isolate("compaction").get("compactionThreshold").resolve(null));  // { percent: 70, ratio: 0.7, source: "global" }'
```

## Rules learned the hard way

- A volatile **array** is fine (`perModel`), a volatile field **inside** an array is rejected by
  dsh's schema (`volatile fields require a fixed object path`). Keep the shape as is.
- Values arrive as reactive refs (`.get()`) through dsh's Loader and as plain values through raw
  cordis; `current()` accepts both.

MIT.
