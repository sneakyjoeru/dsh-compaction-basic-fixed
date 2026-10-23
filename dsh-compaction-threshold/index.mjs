/**
 * dsh-compaction-threshold — the user-editable compaction trigger for the DeepSeek Harness.
 *
 * One host-plane plugin that owns the setting "at what percentage of the routed model's
 * context window does compaction start", globally and per exact provider/model route.
 * Both fields are `volatile`, so the Settings API (and the context-meter popup patch)
 * can change them live without remounting anything, and they are persisted by dsh in
 * the profile's `cordis.patch.yml` like every other setting.
 *
 * The value is a PERCENTAGE OF THE ROUTED MODEL'S CONTEXT WINDOW — never a token count.
 * 80 means "compact when the next request would reach 80% of whatever window the model
 * that is actually serving this session advertises"; switching the session to a model
 * with a different window moves the trigger with it.
 *
 * Consumer: the compaction backend (`dsh-compaction-basic-fixed`) calls
 * `ctx.get("compactionThreshold")?.resolve(target)` while resolving each routed policy and
 * uses the returned ratio in place of its static `thresholdRatio`. The service is optional
 * on both sides: without the backend the setting is inert; without this plugin the backend
 * keeps its configured ratio.
 *
 * Mounted by file URL (no package install):
 *   - insert:
 *     - id: compaction-threshold
 *       name: /volume1/docker/dsh/home/plugins/dsh-compaction-threshold/index.mjs
 *
 * The entry id `compaction-threshold` IS the settings namespace the browser edits.
 */
import { Service } from "@deepseek-ai/cordis";
import z from "@deepseek-ai/schemastery";

/** Inclusive bounds of the percentage. 100 = "only the output reservation caps the prompt". */
export const MIN_PERCENT = 1;
export const MAX_PERCENT = 100;
/** Default: 80% of the routed model's context window. */
export const DEFAULT_PERCENT = 80;

/** Settings namespace (= the host-plane entry id this plugin is mounted under). */
export const name = "compaction-threshold";

/**
 * Normalise a candidate percentage: finite, within bounds, at most 2 decimals.
 * @param {unknown} value
 * @returns {number | undefined} the percentage, or undefined when unusable.
 */
export function normalizePercent(value) {
	const n = typeof value === "string" ? Number.parseFloat(value.replace(",", ".")) : value;
	if (typeof n !== "number" || !Number.isFinite(n)) return undefined;
	const rounded = Math.round(n * 100) / 100;
	if (rounded < MIN_PERCENT || rounded > MAX_PERCENT) return undefined;
	return rounded;
}

/**
 * Pure precedence: exact provider/model override → global → built-in default.
 * Exported so the browser-side patch and tests can mirror the server exactly.
 * @param {{ thresholdPercent?: unknown, perModel?: unknown }} value - settings value.
 * @param {{ provider: string, model: string } | null | undefined} target - routed target.
 * @returns {{ percent: number, ratio: number, source: "model" | "global" | "default" }}
 */
export function resolveThreshold(value, target) {
	const rows = Array.isArray(value?.perModel) ? value.perModel : [];
	if (target) {
		for (const row of rows) {
			if (!row || row.provider !== target.provider || row.model !== target.model) continue;
			const percent = normalizePercent(row.thresholdPercent);
			if (percent !== undefined) return { percent, ratio: percent / 100, source: "model" };
		}
	}
	const global = normalizePercent(value?.thresholdPercent);
	if (global !== undefined) return { percent: global, ratio: global / 100, source: "global" };
	return { percent: DEFAULT_PERCENT, ratio: DEFAULT_PERCENT / 100, source: "default" };
}

const PerModelSchema = z.object({
	provider: z.string().min(1).required().description("Exact provider id of the route (as shown in the model picker)."),
	model: z.string().min(1).required().description("Exact model id of the route."),
	thresholdPercent: z.number().min(MIN_PERCENT).max(MAX_PERCENT).required().description("Compaction trigger for this route, as a percentage of ITS context window."),
}).description("One exact provider/model override.");

/** Singleton settings owner; the compaction backend reads it per routed request. */
export class CompactionThreshold extends Service {
	static Config = z.object({
		thresholdPercent: z.number().min(MIN_PERCENT).max(MAX_PERCENT).default(DEFAULT_PERCENT).volatile()
			.description("Start compaction when the next request would reach this percentage of the routed model's context window (decimals allowed, e.g. 75.2). Applies to every model without its own row below."),
		perModel: z.array(PerModelSchema).default([]).volatile()
			.description("Per-route overrides. A row wins over the global percentage for exactly that provider/model."),
	}).description("Compaction trigger as a percentage of the model's context window (global + per-model).");

	/** @param {import('@deepseek-ai/cordis').Context} ctx @param {any} config */
	constructor(ctx, config) {
		super(ctx, "compactionThreshold");
		this.config = config;
	}

	/** Detached snapshot of the live settings value. */
	current() {
		// dsh's Loader hands volatile fields over as reactive refs (`.get()`); a raw cordis mount
		// (tests, other hosts) hands plain values. Accept both so the service never throws.
		const read = (field) => (field !== null && typeof field === "object" && typeof field.get === "function" ? field.get() : field);
		const perModel = read(this.config?.perModel);
		return {
			thresholdPercent: read(this.config?.thresholdPercent),
			perModel: Array.isArray(perModel) ? perModel.map((row) => ({ ...row })) : [],
		};
	}

	/**
	 * Effective trigger for one routed target.
	 * @param {{ provider: string, model: string } | null | undefined} target
	 */
	resolve(target) {
		return resolveThreshold(this.current(), target);
	}
}

export default CompactionThreshold;
