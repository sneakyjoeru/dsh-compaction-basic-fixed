#!/usr/bin/env python3
"""dsh NAS patch (2026-10-27): the context-meter popup states the IMAGE recognition
price in tokens for the local Qwen vision routes.

Why: dsh prices an image block as its JSON reference (a few tokens) because the
pi-ai adapter declares no image pricing; the engine really charges vision tokens
(measured on the B70 2026-10-27, qwen3.8-27b-heretic-uncensored, one 8-token
completion each):

    1920x1080 -> 2,042 prompt tokens   1280x720 -> 882
     640x480  -> 302                  3840x2160 -> 8,162

    => ~ w*h/1024 tokens per image (one token per 32x32 px) + a few template
       tokens. The provider's `usage` carries them after the first send, so the
       meter's anchored number is right once an image has been sent; this hint
       makes the price visible BEFORE sending.

Contract: runs AFTER meter-compaction-percent.py (it edits that patch's popup
editor component). Cosmetic and skippable: a missing anchor prints SKIPPED,
writes /opt/nas-patches/SKIPPED-meter-image-price and exits 0, exactly like the
meter patch (an upgrade must never fail the image build over a hint).
Idempotent through the marker.
"""
import os
import sys

MARK = "/* NAS meter-image-price v1 */"
SKIP_FILE = "/opt/nas-patches/SKIPPED-meter-image-price"
DEFAULT = (
    "/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/"
    "dsh-client-ui-conversation/lib/client.js"
)
HINT_TEXT = (
    "Images: Qwen vision ~1 token / 1,024 px - 1920x1080 ~2.0K, "
    "1280x720 ~0.9K, 640x480 ~0.3K; usage includes them after the first send"
)

p = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
s = open(p, encoding="utf-8").read()
if MARK in s:
    print("meter-image-price: already patched")
    sys.exit(0)

ANCHOR = '\t\t\t\t\t}),\n\t\t\t\t\troute && (0, react_jsx_runtime.jsxs)("label", {'
count = s.count(ANCHOR)
if count != 1:
    msg = f"meter-image-price: SKIPPED (editor anchor found {count} times, expected 1) - the popup keeps its current layout; the setting still works"
    print(msg, file=sys.stderr)
    try:
        os.makedirs(os.path.dirname(SKIP_FILE), exist_ok=True)
        open(SKIP_FILE, "w").write(msg + "\n")
    except OSError:
        pass
    sys.exit(0)

HINT = (
    '\t\t\t\t\t}),\n'
    '\t\t\t\t\troute && String(route.provider).startsWith("shaitan") && (0, react_jsx_runtime.jsx)("div", {\n'
    '\t\t\t\t\t\tstyle: __nasEditorStyle.hint,\n'
    f'\t\t\t\t\t\tchildren: "{HINT_TEXT}" {MARK}\n'
    '\t\t\t\t\t}),\n'
    '\t\t\t\t\troute && (0, react_jsx_runtime.jsxs)("label", {'
)
s = s.replace(ANCHOR, HINT, 1)
open(p, "w", encoding="utf-8").write(s)
print(f"meter-image-price: patched {p}")
