"""PreToolUse hook: keep agents away from the answer key and raw evidence.

Blocks (exit 2) any Edit/Write to data/raw/ or a score file, and shell commands
that look like they modify those paths. Reading is always allowed.
"""

import json
import re
import sys

PROTECTED = re.compile(r"(data/raw/|data/truth/|outputs/[^\s\"']*/score(card)?\.json)")
MUTATING = re.compile(r"(\brm\b|\bmv\b|\bcp\b[^|]*\s\S*data/raw|>|\bsed\s+-i|\btruncate\b|\bchmod\b|\btee\b|\bunlink\b)")

event = json.load(sys.stdin)
tool, args = event.get("tool_name", ""), event.get("tool_input", {})

if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
    path = args.get("file_path", "") or args.get("notebook_path", "")
    if PROTECTED.search(path):
        print(f"Blocked: {path} is raw evidence or a score. Re-run proveit.fetch or proveit.score instead.", file=sys.stderr)
        sys.exit(2)
elif tool == "Bash":
    cmd = args.get("command", "")
    allowed = any(m in cmd for m in ("proveit.fetch", "proveit.score", "proveit.truth", "score_layer.py"))
    if PROTECTED.search(cmd) and MUTATING.search(cmd) and not allowed:
        print("Blocked: this command may modify raw evidence or a score file.", file=sys.stderr)
        sys.exit(2)
sys.exit(0)
