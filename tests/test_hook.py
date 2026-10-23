import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "protect.py"


def run(event: dict) -> int:
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), text=True, capture_output=True).returncode


def test_blocks_writes_to_raw_data_and_scores():
    assert run({"tool_name": "Write", "tool_input": {"file_path": "/p/data/raw/fire_ems/x.json"}}) == 2
    assert run({"tool_name": "Edit", "tool_input": {"file_path": "/p/outputs/fire_ems/score.json"}}) == 2
    assert run({"tool_name": "Bash", "tool_input": {"command": "rm -rf data/raw/flood_ida"}}) == 2


def test_allows_reads_code_edits_and_refetch():
    assert run({"tool_name": "Bash", "tool_input": {"command": "head data/raw/flood_ida/manifest.json"}}) == 0
    assert run({"tool_name": "Edit", "tool_input": {"file_path": "/p/pro/fire_ems.py"}}) == 0
    assert run({"tool_name": "Bash", "tool_input": {"command": "python3 -m proveit.fetch fire_ems --force"}}) == 0


def test_truth_records_and_scorecards_are_protected():
    assert run({"tool_name": "Write", "tool_input": {"file_path": "/p/data/truth/x/abc.json"}}) == 2
    assert run({"tool_name": "Edit", "tool_input": {"file_path": "/p/outputs/score/run/scorecard.json"}}) == 2
    assert run({"tool_name": "Bash", "tool_input": {"command": "python3 -m proveit.truth get nyc_dob_now_permits"}}) == 0
