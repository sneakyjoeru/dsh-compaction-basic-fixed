#!/usr/bin/env node
/**
 * Unit check for the loader + threshold overlay. Exits 0 with ALL PASS.
 *   node /volume1/docker/dsh/home/plugins/dsh-compaction-basic-fixed/verify.mjs
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import * as mod from "./index.mjs";
import { resolveThreshold, normalizePercent } from "../dsh-compaction-threshold/index.mjs";

const require = createRequire(import.meta.url);
const shipped = require("@deepseek-ai/dsh-compaction-basic");

// 1. loader picked a class that extends the engine and keeps the static plugin contract
assert.equal(typeof mod.default, "function", "default export is the plugin class");
assert.deepEqual(mod.default.inject, shipped.BasicCompactionEngine.inject, "inject list inherited from the engine");
assert.ok(mod.default.Config, "static Config inherited");
assert.ok(new Set(Object.keys(mod.default.Config.dict)).has("thresholdRatio"), "Config schema still declares thresholdRatio");
console.log("provenance:", mod.provenance);

// 2. precedence of the setting
assert.deepEqual(resolveThreshold({ thresholdPercent: 70, perModel: [{ provider: "p", model: "m", thresholdPercent: 55.5 }] }, { provider: "p", model: "m" }), { percent: 55.5, ratio: 0.555, source: "model" });
assert.deepEqual(resolveThreshold({ thresholdPercent: 70, perModel: [] }, { provider: "p", model: "m" }), { percent: 70, ratio: 0.7, source: "global" });
assert.deepEqual(resolveThreshold({}, { provider: "p", model: "m" }), { percent: 80, ratio: 0.8, source: "default" });
assert.equal(normalizePercent("75,2"), 75.2);
assert.equal(normalizePercent(0), undefined);
assert.equal(normalizePercent(100), 100);
assert.equal(normalizePercent("x"), undefined);

// 3. overlay onto a resolved static config
const base = Object.freeze({
	thresholdRatio: 0.8, headroomTokens: 0, retainRatio: 0.2, maxTokens: 4096,
	compactionRetries: 1, maxOverflowRetries: 1, summarizationProvider: "", summarizationModel: "",
	modelPolicies: Object.freeze([Object.freeze({ provider: "p", model: "static", maxTokens: 2048 })]), auto: true,
});
let out = mod.overlayThreshold(base, { thresholdPercent: 75.2, perModel: [{ provider: "p", model: "m", thresholdPercent: 60 }] });
assert.equal(out.thresholdRatio, 0.752, "global ratio from percent");
assert.equal(out.retainRatio, 0.2, "retention untouched when below trigger");
assert.equal(out.maxTokens, 4096, "other fields pass through");
const byKey = Object.fromEntries(out.modelPolicies.map((p) => [`${p.provider}/${p.model}`, p]));
assert.equal(byKey["p/m"].thresholdRatio, 0.6, "per-model row became a modelPolicies override");
assert.equal(byKey["p/static"].thresholdRatio, 0.752, "static policy without own threshold inherits live global");
assert.equal(byKey["p/static"].maxTokens, 2048, "static policy keeps its own fields");

// 4. retention is forced below a low user threshold instead of tripping the per-target guard
out = mod.overlayThreshold(base, { thresholdPercent: 15, perModel: [{ provider: "p", model: "m", thresholdPercent: 10 }] });
assert.equal(out.thresholdRatio, 0.15);
assert.equal(out.retainRatio, 0.0375, "retainRatio clamped to 25% of the trigger");
assert.equal(Object.fromEntries(out.modelPolicies.map((p) => [p.model, p])).m.retainRatio, 0.025, "per-model retention clamped too");

// 5. no service value -> static config semantics preserved (default 80 applies, nothing else moves)
out = mod.overlayThreshold(base, {});
assert.equal(out.thresholdRatio, 0.8);
assert.equal(out.modelPolicies.length, 1);

console.log("ALL PASS");
