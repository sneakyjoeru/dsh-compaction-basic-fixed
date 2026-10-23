#!/usr/bin/env python3
"""dsh NAS patch v2 (2026-10-23; v1 2026-10-04/05): the composer context meter follows the LIVE
compaction trigger and lets the user edit it from the context popup.

Target: @deepseek-ai/dsh-client-ui-conversation/lib/client.js (the browser bundle dsh-web serves).

WHAT CHANGES
  1. Ring / percentage: `used / contextWindow` -> `used / (contextWindow * ratio)`, so 100% is the
     barrier at which compaction fires. v1 hardcoded ratio 0.8; v2 reads it from the
     `compaction-threshold` settings namespace (plugin $DSH_HOME/plugins/dsh-compaction-threshold,
     volatile fields `thresholdPercent` + `perModel[]`) through the client's configForms service,
     resolving per-model -> global -> 80 exactly like the server (`resolveThreshold`). Without the
     plugin the form is "unavailable" and the meter falls back to 0.8 (v1 behaviour).
  2. Figures line: `~used / ratio*window (max window)` so the number agrees with the percentage.
  3. Popup editor (new): a text field "Compact at [ 80 ]% of context" accepting decimals (75.2 or
     75,2; 1..100), a hint with the trigger in tokens for the model that is actually routed
     (`modelSelection.next ?? lastUsed`), and a checkbox "only for <provider/model>" that stores the
     value as a per-route override instead of the global one. Enter/blur saves through
     `form.mutate([...], revision)`; Escape reverts. Hidden when the namespace is not served.

  The percentage is ALWAYS a fraction of the routed model's advertised context window — the default
  80 is not a token count and moves with the model.

RESILIENCE (owner request 2026-10-23: upgrades must not block work)
  This patch is COSMETIC: the setting itself works through Settings even without it. So when an
  anchor is missing on a newer dsh it prints a loud "SKIPPED" line, writes
  /opt/nas-patches/SKIPPED-meter-compaction-percent and exits 0 instead of failing the image build.
  (The other NAS patches keep their fail-loud contract; this one is the exception by design.)
  Idempotent: every edit sits behind a marker.

Usage: meter-compaction-percent.py [path-to-client.js]   (default: locate it under /usr/local/lib)
       METER_PATCH_STRICT=1 restores exit 1 on a missing anchor (used by the local self-test).
"""
import glob
import os
import re
import sys

MARK = "/* NAS meter-compaction-percent v2 */"
SKIP_FILE = "/opt/nas-patches/SKIPPED-meter-compaction-percent"
STRICT = os.environ.get("METER_PATCH_STRICT") == "1"
NAMESPACE = "compaction-threshold"
FALLBACK_RATIO = "0.8"

paths = sys.argv[1:] or glob.glob(
    "/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/"
    "dsh-client-ui-conversation/lib/client.js"
)
if not paths:
    sys.exit("meter-compaction-percent: dsh-client-ui-conversation/lib/client.js not found")
p = paths[0]
s = open(p, encoding="utf-8").read()
original = s

if MARK in s:
    print("meter-compaction-percent: already patched (v2 marker present)")
    sys.exit(0)
if "/* NAS meter-compaction-percent patch" in s or "/* NAS meter-figures patch */" in s:
    sys.exit("meter-compaction-percent: v1 markers present; apply v2 to a pristine bundle")


def skip(reason):
    msg = f"meter-compaction-percent: SKIPPED ({reason}) - meter keeps upstream behaviour; the compaction-threshold setting still works via Settings"
    if STRICT:
        sys.exit(msg)
    print(msg, file=sys.stderr)
    try:
        os.makedirs(os.path.dirname(SKIP_FILE), exist_ok=True)
        open(SKIP_FILE, "w").write(msg + "\n")
    except OSError:
        pass
    sys.exit(0)


def replace_once(text, anchor, replacement, what, regex=False):
    if regex:
        matches = list(re.finditer(anchor, text))
        if len(matches) != 1:
            skip(f"{what}: anchor found {len(matches)} times (expected 1)")
        m = matches[0]
        return text[: m.start()] + replacement(m) + text[m.end():]
    count = text.count(anchor)
    if count != 1:
        skip(f"{what}: anchor found {count} times (expected 1)")
    return text.replace(anchor, replacement, 1)


# ----------------------------------------------------------------------------------------------
# 1. contextOccupancy(pressure) -> contextOccupancy(pressure, ratio): percentage against the trigger
# ----------------------------------------------------------------------------------------------
s = replace_once(
    s,
    "function contextOccupancy(pressure) {",
    f"function contextOccupancy(pressure, ratio = {FALLBACK_RATIO}) {{ {MARK}",
    "occupancy signature",
)
s = replace_once(
    s,
    "percent: Math.min(100, Math.round(usedTokens / pressure.contextWindow * 100)),",
    "percent: Math.min(100, Math.round(usedTokens / (pressure.contextWindow * ratio) * 100)),\n\t\t\t\tratio,",
    "occupancy percent",
)

# ----------------------------------------------------------------------------------------------
# 2. Module-level glue + the popup editor component, inserted right before ContextMeter.
# ----------------------------------------------------------------------------------------------
HELPERS = r'''
		// ---- NAS meter-compaction-percent v2: live compaction trigger (settings namespace "compaction-threshold") ----
		/** Set once by apply(): the configForms scope of the compaction-threshold plugin, or null when it cannot be obtained. */
		let __nasThresholdForm = null;
		/** Stable subscribe/getSnapshot pair for useSyncExternalStore (identity must not change per render). */
		let __nasThresholdStore = null;
		const __nasAbsentSnapshot = Object.freeze({ status: "unavailable", value: void 0, base: void 0, user: void 0, revision: void 0, writable: false });
		const __nasAbsentStore = { subscribe: () => () => {}, getSnapshot: () => __nasAbsentSnapshot };
		/** Mirror of the server's normalizePercent: finite, 1..100, at most 2 decimals; comma accepted. */
		function __nasNormalizePercent(value) {
			const n = typeof value === "string" ? Number.parseFloat(value.replace(",", ".")) : value;
			if (typeof n !== "number" || !Number.isFinite(n)) return void 0;
			const rounded = Math.round(n * 100) / 100;
			if (rounded < 1 || rounded > 100) return void 0;
			return rounded;
		}
		/** Mirror of the server's resolveThreshold: exact route row -> global -> 80 (a ratio of the model's window). */
		function __nasResolveThreshold(value, route) {
			const rows = Array.isArray(value?.perModel) ? value.perModel : [];
			if (route) for (const row of rows) {
				if (!row || row.provider !== route.provider || row.model !== route.model) continue;
				const percent = __nasNormalizePercent(row.thresholdPercent);
				if (percent !== void 0) return { percent, ratio: percent / 100, source: "model" };
			}
			const global = __nasNormalizePercent(value?.thresholdPercent);
			if (global !== void 0) return { percent: global, ratio: global / 100, source: "global" };
			return { percent: 80, ratio: .8, source: "default" };
		}
		const __nasEditorStyle = {
			root: { borderTop: "1px solid var(--dsw-alias-border-l1)", marginTop: 10, paddingTop: 10, display: "flex", flexDirection: "column", gap: 6 },
			row: { display: "flex", alignItems: "center", gap: 6, color: "var(--dsw-alias-label-secondary)" },
			input: { width: 56, boxSizing: "border-box", padding: "1px 6px", font: "inherit", fontVariantNumeric: "tabular-nums", textAlign: "right", color: "var(--dsw-alias-label-primary)", background: "var(--dsw-alias-interactive-bg-hover)", border: "1px solid var(--dsw-alias-border-l2)", borderRadius: "var(--dsw-radius-sm)", outline: "none" },
			inputInvalid: { borderColor: "var(--dsw-static-red-500, #e5484d)" },
			hint: { color: "var(--dsw-alias-label-tertiary)", fontVariantNumeric: "tabular-nums" },
			check: { display: "flex", alignItems: "center", gap: 6, color: "var(--dsw-alias-label-secondary)", cursor: "pointer", minWidth: 0 },
			checkLabel: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 },
			error: { color: "var(--dsw-static-red-500, #e5484d)" }
		};
		/**
		* Popup editor for the compaction trigger. Writes the `compaction-threshold` namespace through the
		* configForms scope; renders nothing while the namespace is not served (plugin absent).
		*/
		function __NasCompactionThresholdEditor({ form, snapshot, route, threshold, contextWindow, t }) {
			const ready = form !== null && snapshot.status === "ready";
			const [draft, setDraft] = (0, react.useState)(null);
			const [state, setState] = (0, react.useState)("idle");
			const routeKey = route ? `${route.provider}\0${route.model}` : "";
			(0, react.useEffect)(() => {
				setDraft(null);
				setState("idle");
			}, [routeKey, threshold.percent, threshold.source]);
			if (!ready) return null;
			const shown = draft ?? String(threshold.percent);
			const parsed = __nasNormalizePercent(shown);
			const invalid = parsed === void 0;
			const perModel = threshold.source === "model";
			const trigger = Math.floor(contextWindow * (invalid ? threshold.ratio : parsed / 100));
			const commit = async (percent, scopeToModel) => {
				const value = snapshot.value ?? {};
				const rows = Array.isArray(value.perModel) ? value.perModel : [];
				const others = route ? rows.filter((row) => !(row && row.provider === route.provider && row.model === route.model)) : rows;
				const ops = [];
				if (scopeToModel && route) ops.push({ op: "set", path: ["perModel"], value: [...others, { provider: route.provider, model: route.model, thresholdPercent: percent }] });
				else {
					ops.push({ op: "set", path: ["thresholdPercent"], value: percent });
					if (others.length !== rows.length) ops.push({ op: "set", path: ["perModel"], value: others });
				}
				setState("saving");
				let ok = false;
				try {
					ok = await form.mutate(ops, snapshot.revision);
				} catch {
					ok = false;
				}
				setState(ok ? "idle" : "error");
				if (ok) setDraft(null);
			};
			const save = () => {
				if (invalid || state === "saving") return;
				if (parsed === threshold.percent) {
					setDraft(null);
					return;
				}
				commit(parsed, perModel);
			};
			const routeLabel = route ? `${route.provider}/${route.model}` : "";
			return (0, react_jsx_runtime.jsxs)("div", {
				style: __nasEditorStyle.root,
				"data-nas-compaction-threshold": true,
				children: [
					(0, react_jsx_runtime.jsxs)("label", {
						style: __nasEditorStyle.row,
						children: [
							"Compact at",
							(0, react_jsx_runtime.jsx)("input", {
								type: "text",
								inputMode: "decimal",
								"aria-label": "Compaction trigger, percent of the model's context window",
								"aria-invalid": invalid,
								value: shown,
								disabled: !snapshot.writable || state === "saving",
								style: invalid ? { ...__nasEditorStyle.input, ...__nasEditorStyle.inputInvalid } : __nasEditorStyle.input,
								onChange: (event) => {
									setDraft(event.target.value);
								},
								onKeyDown: (event) => {
									if (event.key === "Enter") {
										event.preventDefault();
										save();
									} else if (event.key === "Escape") {
										event.preventDefault();
										event.stopPropagation();
										setDraft(null);
									}
								},
								onBlur: () => {
									if (draft !== null) save();
								}
							}),
							"% of context"
						]
					}),
					(0, react_jsx_runtime.jsx)("div", {
						style: __nasEditorStyle.hint,
						children: invalid ? "Enter a number between 1 and 100 (decimals allowed, e.g. 75.2)" : `≈ ${formatTokens(trigger, t)} of ${formatTokens(contextWindow, t)} tokens · ${perModel ? "this model" : "all models"}`
					}),
					route && (0, react_jsx_runtime.jsxs)("label", {
						style: __nasEditorStyle.check,
						title: routeLabel,
						children: [(0, react_jsx_runtime.jsx)("input", {
							type: "checkbox",
							checked: perModel,
							disabled: !snapshot.writable || state === "saving",
							onChange: (event) => {
								const percent = invalid ? threshold.percent : parsed;
								commit(percent, event.target.checked);
							}
						}), (0, react_jsx_runtime.jsx)("span", {
							style: __nasEditorStyle.checkLabel,
							children: `only for ${route.model}`
						})]
					}),
					state === "error" && (0, react_jsx_runtime.jsx)("div", {
						style: __nasEditorStyle.error,
						children: "Could not save - the setting changed elsewhere or the host refused it. Reopen and retry."
					})
				]
			});
		}
		// ---- end NAS meter-compaction-percent v2 helpers ----
'''
s = replace_once(
    s,
    "\t\tfunction ContextMeter({ useProjection, t }) {\n\t\t\tconst pressure = useProjection(\"contextPressure\");\n\t\t\tconst breakdown = useProjection(\"contextBreakdown\");\n",
    HELPERS
    + "\t\tfunction ContextMeter({ useProjection, t }) {\n"
    + "\t\t\tconst pressure = useProjection(\"contextPressure\");\n"
    + "\t\t\tconst breakdown = useProjection(\"contextBreakdown\");\n"
    + "\t\t\tconst modelSelection = useProjection(\"modelSelection\"); " + MARK + "\n"
    + "\t\t\tconst thresholdStore = __nasThresholdStore ?? __nasAbsentStore;\n"
    + "\t\t\tconst thresholdSnapshot = (0, react.useSyncExternalStore)(thresholdStore.subscribe, thresholdStore.getSnapshot);\n"
    + "\t\t\tconst route = modelSelection?.next ?? modelSelection?.lastUsed ?? null;\n"
    + "\t\t\tconst threshold = __nasResolveThreshold(thresholdSnapshot.status === \"ready\" ? thresholdSnapshot.value : void 0, route);\n",
    "ContextMeter head",
)
s = replace_once(
    s,
    "\t\t\tconst context = contextOccupancy(pressure);\n",
    "\t\t\tconst context = contextOccupancy(pressure, threshold.ratio);\n",
    "occupancy call",
)

# ----------------------------------------------------------------------------------------------
# 3. Figures line shows the trigger and the real window.
# ----------------------------------------------------------------------------------------------
s = replace_once(
    s,
    "children: `~${formatTokens(context.usedTokens, t)} / ${formatTokens(context.contextWindow, t)}`",
    "children: `~${formatTokens(context.usedTokens, t)} / ${formatTokens(Math.floor(context.contextWindow * context.ratio), t)} (max ${formatTokens(context.contextWindow, t)})` " + MARK,
    "figures",
)

# ----------------------------------------------------------------------------------------------
# 4. Mount the editor as the last child of the popup panel (after the breakdown <dl>).
# ----------------------------------------------------------------------------------------------
PANEL_TAIL = re.compile(
    r"(\}, row\.key\)\)\n\t+\}\)\n)(\t+\]\n\t+\}\), document\.body\)\])"
)
s = replace_once(
    s,
    PANEL_TAIL,
    lambda m: m.group(1)
    + "\t\t\t\t\t\t, (0, react_jsx_runtime.jsx)(__NasCompactionThresholdEditor, { form: __nasThresholdForm, snapshot: thresholdSnapshot, route, threshold, contextWindow: context.contextWindow, t }) " + MARK + "\n"
    + m.group(2),
    "panel tail",
    regex=True,
)

# ----------------------------------------------------------------------------------------------
# 5. apply(ctx): obtain the configForms scope once (the plugin already injects configForms).
# ----------------------------------------------------------------------------------------------
s = replace_once(
    s,
    "\t\t\tconst submissionPolicy = new ComposerSubmissionPolicy(ctx.configForms.get(CONVERSATION_SETTINGS_NAMESPACE));\n",
    "\t\t\tconst submissionPolicy = new ComposerSubmissionPolicy(ctx.configForms.get(CONVERSATION_SETTINGS_NAMESPACE));\n"
    + "\t\t\ttry { " + MARK + "\n"
    + "\t\t\t\tconst thresholdForm = ctx.configForms.get(\"" + NAMESPACE + "\");\n"
    + "\t\t\t\t__nasThresholdForm = thresholdForm;\n"
    + "\t\t\t\t__nasThresholdStore = { subscribe: (listener) => thresholdForm.subscribe(listener), getSnapshot: () => thresholdForm.getSnapshot() };\n"
    + "\t\t\t} catch (error) {\n"
    + "\t\t\t\tconsole.warn(\"compaction-threshold: settings form unavailable; meter falls back to 80%\", error);\n"
    + "\t\t\t}\n",
    "apply hook",
)

if s == original:
    skip("nothing changed")
open(p, "w", encoding="utf-8").write(s)
print(f"meter-compaction-percent v2: patched {p} (5 edits)")
