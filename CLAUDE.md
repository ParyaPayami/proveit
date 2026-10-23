# ProveIt: agent instructions

ProveIt scores any GIS or AI prediction against public records of what actually happened. Use it to check your own analysis before reporting it.

## Check any prediction (the main workflow)
1. Find an answer key: `python3 -m proveit.truth find --bbox W S E N --topic permits` (or `--text "street flooding"`). Read the source's traps in `catalog/<id>.json`.
2. Write a config and score: `bin/pro pro/score_layer.py config.json`. Example config:
   `{"prediction": "C:\\proveit_work\\x.gdb\\areas", "field": "risk", "source": "nyc_dob_now_permits", "where": "work_type='Solar'", "prediction_date": "2025-01-01", "start": "2025-01-01", "end": "2025-12-31", "name": "my_run"}`
3. Read `outputs/score/<name>/scorecard.json`. Report the headline, the metrics, and every trap with status `warning` or `check`. Fix what you can (e.g. move `start` after `prediction_date`), then rerun.
4. A source you need isn't in the catalog? Add one (see `docs/ADD_A_SOURCE.md`). Never fill a gap with invented data.

## How to run things
- ArcPy runs only in Windows. Run a script with `bin/pro pro/<script>.py`. It executes in ArcGIS Pro's Python inside the Parallels VM "Windows 11" and logs every run to `runs/`.
- Scratch geodatabases go in `C:\proveit_work` (local to Windows). Never put a .gdb in this folder (it is a network share there).
- Mac-side Python (`proveit/`) is standard library only. Tests: `.venv/bin/python -m pytest -q tests`.
- Data: `python3 -m proveit.fetch <case>` downloads into `data/raw/<case>/` and records URL, size and SHA-256 in `manifest.json`.
- Score: `python3 -m proveit.score <case>` writes `outputs/<case>/score.json`.

## Rules
1. **Never edit `data/raw/` or a `score.json`.** A hook blocks it. Fix the analysis or re-run fetch/score instead.
2. **Read the case file first** (`cases/<case>.json`): its sources, assumptions and traps define a correct analysis.
3. **Compare like with like.** Before scoring, write down what the observed field measures and what the model measures. If they differ, say so; don't just report a number.
4. **Flag, don't fill.** If data needed for a question is missing or a dataset's limits make it unusable, say so in `run_summary.json` and in your reply. Never substitute made-up or synthetic values.
5. **Record provenance.** Every Pro script writes `run_summary.json` using `common.provenance(...)`.
6. **Report results honestly**, including bias, excluded areas and the worst-fitting places.

## Layout
- `cases/` case definitions: sources, answer key, assumptions, traps
- `pro/` ArcPy scripts (run in Pro); `pro/ProveIt.pyt` toolbox for people
- `proveit/` bridge, fetch, score (Mac)
- `outputs/<case>/` results; `runs/` logs of every Pro run
