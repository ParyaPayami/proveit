---
name: prove-it
description: Score a GIS or AI prediction (points, polygons or raster) against public records of what really happened, using the ProveIt truth catalog and Score My Layer in ArcGIS Pro, or run a proof case. Use when asked to validate, check, or test a spatial analysis or model.
---

# Scoring any prediction

1. `python3 -m proveit.truth find --bbox W S E N --topic <topic>` to pick a source. Read its traps.
2. Fix the prediction date. Outcomes must come after it (`start` >= `prediction_date`).
3. `bin/pro pro/score_layer.py config.json`, then read `outputs/score/<name>/scorecard.json` and `report.html`.
4. Report the headline, the metrics, and all `warning` and `check` traps. Rerun after fixing what you can.

# Running a ProveIt proof case

1. **Read the case.** Open `cases/<case>.json`. Note the question, the observed field (what reality measured), the assumptions, and every trap.
2. **Get the evidence.** Run `python3 -m proveit.fetch <case>`. Check `data/raw/<case>/manifest.json` for sizes and hashes. Don't modify raw files.
3. **Write down the comparison** before any analysis. One sentence each: what the model will measure, what the observed field measures, and where they differ.
4. **Analyze in Pro.** Put the ArcPy in `pro/<case>.py` and run `bin/pro pro/<case>.py`. Use `common.work_gdb()` for scratch data and `common.provenance()` in `run_summary.json`. Include evidence for each trap: the field used, the filters applied, what was excluded and why.
5. **Score independently.** Run `python3 -m proveit.score <case>`. Never compute the score inside the analysis script, and never edit `score.json`.
6. **Report:**
   - agreement (r, bias, MAE, share within tolerance) against the observed field;
   - what the careless comparison would have shown;
   - excluded areas and the largest gaps;
   - each trap, caught or not;
   - assumptions that could explain the bias.
7. **Leave a tool behind.** If the analysis is accepted, expose it as a tool in `pro/ProveIt.pyt` so it can be rerun from the Geoprocessing pane.

If evidence for a step is missing, stop and say what is missing. Never invent data.
