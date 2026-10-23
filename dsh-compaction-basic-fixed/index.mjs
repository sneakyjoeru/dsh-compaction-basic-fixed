/**
 * dsh-compaction-basic-fixed — stable entry point for the compaction backend.
 *
 * WHY A LOADER (2026-10-23, owner request: "plugins must survive future DSH upgrades and never
 * block work"). The long-session fixes live in a full copy of the shipped
 * `@deepseek-ai/dsh-compaction-basic` and are therefore pinned to ONE dsh version. Pointing the
 * profile at a version-named copy meant that after a dsh bump the row either loaded a stale copy
 * against new internals or failed to activate — and a dead compaction row kills every long
 * session. This file is the one path the profile mounts; it decides at import time:
 *
 *   1. `versions/<installed dsh-compaction-basic version>/lib/index.js` exists
 *        -> load that re-based copy (long-session fixes + 80% defaults active).
 *   2. otherwise
 *        -> load the SHIPPED `@deepseek-ai/dsh-compaction-basic` of the running dsh and log a
 *           warning once. Compaction keeps working on upstream behaviour (same config schema, so
 *           the preset row stays valid); only the three local fixes are inactive until someone
 *           re-bases a copy into `versions/<new version>/` (see README).
 *
 * In both cases the exported plugin is a thin subclass that overlays the LIVE compaction
 * threshold from the optional `compactionThreshold` service (plugin `dsh-compaction-threshold`,
 * the user-editable "compact at N% of the model's context window" setting, global + per model).
 * The overlay works through a `config` accessor, so it needs no edit inside either copy and
 * survives upstream refactors as long as `BasicCompactionEngine` keeps reading
 * `this.config.{thresholdRatio,retainRatio,retainTokens,modelPolicies}` — the public config
 * contract documented in its README.
 *
 * Mount (profile cordis.patch.yml, preset-plane compaction group; the sync script emits it):
 *   - id: compaction-basic
 *     name: /volume1/docker/dsh/home/plugins/dsh-compaction-basic-fixed/index.mjs
 *     config: { thresholdRatio: 0.8, retainRatio: 0.2, headroomTokens: 0, maxTokens: 4096 }
 *
 * Bare imports resolve through the `node_modules` symlink next to this file
 * (-> /usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules), which is version-independent.
 */
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { resolveThreshold } from "../dsh-compaction-threshold/index.mjs";

const require = createRequire(import.meta.url);

/** Installed (shipped) compaction-basic version — the version our copy must match. */
const shippedVersion = require("@deepseek-ai/dsh-compaction-basic/package.json").version;
const copyUrl = new URL(`./versions/${shippedVersion}/lib/index.js`, import.meta.url);
const hasCopy = existsSync(fileURLToPath(copyUrl));

const baseModule = hasCopy ? await import(copyUrl.href) : await import("@deepseek-ai/dsh-compaction-basic");
const Base = baseModule.BasicCompactionEngine ?? baseModule.default;
if (typeof Base !== "function") throw new Error("dsh-compaction-basic-fixed: base module exports no BasicCompactionEngine class");

/** Human-readable provenance, logged once per plugin instance. */
export const provenance = hasCopy
	? `fixed copy versions/${shippedVersion} (long-session fixes active)`
	: `SHIPPED @deepseek-ai/dsh-compaction-basic ${shippedVersion} — no re-based copy in versions/${shippedVersion}; long-session fixes INACTIVE, compaction itself works`;

// One stderr line per process so $DSH_HOME/dsh-web.log records which path is active after an upgrade
// (plugin logger.info is not mirrored there). grep: "compaction-basic-fixed:"
process.stderr.write(`compaction-basic-fixed: ${provenance}\n`);

/** Fraction of the trigger kept verbatim when a user-chosen threshold undercuts the configured retainRatio. */
const RETAIN_FRACTION_OF_THRESHOLD = 0.25;

/**
 * Keep retention strictly below the trigger: compaction-basic rejects `retainRatio >= thresholdRatio`
 * per target, which a low user threshold (e.g. 15%) would otherwise trip on every step.
 * @param {{retainRatio?: number, retainTokens?: number}} policy
 * @param {number} ratio
 */
function retentionBelow(policy, ratio) {
	if (policy.retainTokens !== undefined) return {};
	if (policy.retainRatio === undefined || policy.retainRatio < ratio) return {};
	return { retainRatio: Math.round(ratio * RETAIN_FRACTION_OF_THRESHOLD * 1e4) / 1e4 };
}

/**
 * Compose the effective config: the resolved static config with the live threshold layered on.
 * @param {any} base - frozen config produced by the engine's own `resolveConfig`.
 * @param {{thresholdPercent?: number, perModel?: Array<{provider:string,model:string,thresholdPercent:number}>}} live
 */
export function overlayThreshold(base, live) {
	const global = resolveThreshold(live, null).ratio;
	const policies = new Map();
	for (const policy of base.modelPolicies ?? []) policies.set(`${policy.provider}\0${policy.model}`, { ...policy });
	for (const row of Array.isArray(live?.perModel) ? live.perModel : []) {
		if (!row || typeof row.provider !== "string" || typeof row.model !== "string") continue;
		const { ratio, source } = resolveThreshold(live, row);
		if (source !== "model") continue;
		const key = `${row.provider}\0${row.model}`;
		const existing = policies.get(key) ?? { provider: row.provider, model: row.model };
		policies.set(key, { ...existing, thresholdRatio: ratio });
	}
	// Static per-model rows without their own threshold inherit the live global one.
	for (const policy of policies.values()) {
		if (policy.thresholdRatio === undefined) policy.thresholdRatio = global;
		Object.assign(policy, retentionBelow({ ...base, ...policy }, policy.thresholdRatio));
	}
	return {
		...base,
		thresholdRatio: global,
		...retentionBelow(base, global),
		modelPolicies: [...policies.values()],
	};
}

/** The mounted plugin: the chosen base engine plus the live threshold overlay. */
export class CompactionBasicFixed extends Base {
	constructor(ctx, config = {}) {
		super(ctx, config);
		const staticConfig = this.config;
		ctx.logger?.info?.(`compaction-basic-fixed: ${provenance}`);
		if (!hasCopy) ctx.logger?.warn?.(`compaction-basic-fixed: re-base the local copy for dsh-compaction-basic ${shippedVersion} (see plugins/dsh-compaction-basic-fixed/README.md)`);
		// The base class declares `config` as an own data field; replace it with an accessor so every
		// `resolveTargetPolicy(this.config, target)` sees the live threshold without touching its code.
		Object.defineProperty(this, "config", {
			configurable: true,
			enumerable: true,
			get: () => {
				const service = ctx.get("compactionThreshold");
				if (service === undefined) return staticConfig;
				try {
					return overlayThreshold(staticConfig, service.current());
				} catch (error) {
					ctx.logger?.warn?.(`compaction-basic-fixed: threshold overlay failed (${error instanceof Error ? error.message : String(error)}); using static config`);
					return staticConfig;
				}
			},
		});
	}
}

export { CompactionBasicFixed as BasicCompactionEngine };
export default CompactionBasicFixed;
