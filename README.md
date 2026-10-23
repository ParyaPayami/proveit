# ProveIt

**Score any GIS or AI prediction against public records of what really happened.** An ArcGIS Pro toolbox, a catalog of truth sources, and proof cases showing the scoring is right.

## The toolbox (`pro/ProveIt.pyt`)
1. **Find Truth Sources:** public outcome records that cover your area and topic, each with its traps.
2. **Get Truth Records:** downloads a source for your study area and dates, with a data fingerprint.
3. **Score My Layer:** scores a prediction layer (points, polygons or raster) against a source. It matches places and dates, picks the right test, checks traps, and writes a scorecard, an HTML report and a layer showing where the model was wrong.

| Prediction | event / presence | measure | label (yes/no) | area totals |
|---|---|---|---|---|
| polygons | count per polygon | median per polygon | share yes (yes/no if one record each) | join by code |
| points | any record within distance (yes/no) | nearest within distance | nearest within distance | join by code |
| raster | values at records vs random controls | value at records | value at records | |

Every scorecard includes automatic trap checks:
- **Hindsight:** outcomes dated before the prediction.
- **Truncated downloads:** the source hit its row limit.
- **Unmatched records:** records outside every prediction feature.
- **Excluded labels:** what the score would be if they were counted as "no".
- **Presence-only data:** records exist only where the outcome happened.
- **Small samples.**
- **The source's documented pitfalls.**

## Truth catalog (`catalog/`, 15 sources)

| Topic | Sources |
|---|---|
| **Permits & development** | NYC DOB NOW permits (incl. solar), NYC legacy DOB permits, NYC certificates of occupancy, Chicago building permits, San Francisco building permits |
| Emergency response | FDNY fire and EMS travel times by ZIP |
| Flood | USGS Ida high-water marks, NYC FloodNet sensor events, NYC 311 flooding complaints; any USGS flood (manual, API to verify) |
| Wildfire | CAL FIRE damage inspections, Eaton and Palisades 2025 |
| Buildings & energy | NYC LL84 energy benchmarking |
| Manual | EAGLE-I power outages, Tracking the Sun solar installs |

To add a source, see `docs/ADD_A_SOURCE.md`. Adapters cover Socrata portals (most US cities), ArcGIS feature layers and CSV files.

## Proof that it works (October 22, 2026, ArcGIS Pro 3.7)

| Proof | Result |
|---|---|
| **Known answers** | A field holding the true outcome scores Spearman **1.0**; a random field scores near 0 (0.08 NYC, −0.22 Chicago) |
| **Reproduces purpose-built analyses** | Wildfire, slope: AUC **0.581** (case script 0.581). Open-land distance: **0.379** (0.379). Flood sink depth via the raster path: 0.754 with controls anywhere (case 0.729 with controls near marks) |
| **PlanArena forecast, independent records** | PlanArena's 2020 five-year redevelopment probabilities for 42,170 Manhattan lots, scored against records it never trained on: new-building starts 2021–25 AUC **0.81** (soft-site rule 0.81); completions on lots without a recent building AUC **0.67** (soft-site rule 0.39). The trap check caught frontage geocoding (30 of 601 certificates inside a lot), completion lag and condo billing BBLs (`pro/proof_planarena.py`) |
| **Permits, NYC solar** | Last two years' solar permits per ZIP area predicted 2025: Spearman **0.97**; the top 20% of areas held 59% of 8,438 permits (the best possible was 61%) |
| **Permits, Chicago new construction** | 2021–23 permits per community area predicted 2024–25: Spearman **0.94**; the top 20% held 64% of 2,697 (best possible 65%) |

The three original reference cases (`cases/`, `pro/fire_ems.py`, `pro/flood_ida.py`, `pro/wildfire_la.py`) are proof cases too:

| Case | Answer key | Result |
|---|---|---|
| Fire coverage, NYC | FDNY travel times, 167 ZIP areas | Model too fast by a median 2.2 min; r = 0.48; 92% within ±1 min after removing that bias, also when the bias is estimated out of sample (leave-one-out) |
| Ida flood, NYC 2021 | 159 USGS high-water marks | Marks 4.2× more likely in a terrain low spot; site AUC 0.81; depth Spearman 0.35 on 142 street marks (10 reviewed indoor marks excluded) |
| Wildfire, LA 2025 | 30,399 inspected structures | The textbook "near open land is riskier" rule reversed (AUC 0.38) |

## Agent evaluation (October 23, 2026)
32 tasks, one fresh Claude Code agent each, working in ArcGIS Pro without the reference answers. All 32 met their pre-registered checks: 8 known answers, 14 observed outcomes and 10 traps (3 refused, 5 redirected, 2 completed with a warning). The agents found six flaws in the reference analysis, all now fixed:
- **ZIP 11249:** restored to the fire comparison.
- **Area roll-up:** Score My Layer can combine postal ZIPs into multi-ZIP areas (`key_members`).
- **Bias correction:** now also reported out of sample (leave-one-out).
- **Indoor flood marks:** a reviewed list of 10 replaces a keyword rule that flagged 31.
- **Study area:** the fire tool takes a study-area prefix.
- **Wildfire limits:** the open-land and cross-fire limits are now part of the wildfire case.

Details: `outputs/agent_eval/SUMMARY.md`.

## Run
```bash
python3 -m proveit.truth find --bbox -87.7 41.8 -87.6 41.9 --topic permits
python3 -m proveit.truth get chicago_building_permits --start 2025-01-01 --end 2025-12-31 --where "permit_type='PERMIT - NEW CONSTRUCTION'"
bin/pro pro/score_layer.py my_config.json          # see CLAUDE.md for the config keys
bin/pro pro/proof_permits.py && bin/pro pro/proof_reproduce.py
bin/pro pro/check_network.py                       # known-answer check of the network builder
.venv/bin/python -m pytest -q tests
```
In ArcGIS Pro, add `pro/ProveIt.pyt` (it's already attached to `Documents\ArcGIS\Projects\ProveIt\ProveIt.aprx`).

## How it runs
- **Mac side:** the AI agent, the downloads and the scoring, all standard-library Python.
- **Bridge:** `bin/pro` sends scripts to ArcGIS Pro's Python in the Parallels VM `Windows 11`.
- **Logs:** every run is logged to `runs/`. Downloads record URL, time and SHA-256.
- **Separation:** scoring is independent of the analysis code.
- **Guardrail:** a hook stops agents from editing raw evidence, truth records or scorecards.

## Limits
- Scores measure agreement with past outcomes, not cause and effect.
- Truth records have their own gaps, which is why every source lists its traps.
- Persistence forecasts are a baseline any real model should beat, not a model.
- The agent task suite (`tasks/suite.json`, 32 tasks) is ready but hasn't been run with fresh agents yet.

## Play PlanArena
PlanArena is the parcel-level planning model whose forecast is checked in `pro/proof_planarena.py`. Its browser Studio and phone game let you paint land uses onto real Manhattan parcels, see the indicators change, and watch a simulated council vote. **Play it: [planarena-manhattan.onrender.com/play](https://planarena-manhattan.onrender.com/play)** (desktop Studio at [planarena-manhattan.onrender.com](https://planarena-manhattan.onrender.com)). It runs on a free server, so the first visit can take about a minute to wake, and the AI's recommended plan takes about 30 seconds. The demo code is at [github.com/ParyaPayami/planarena-demo](https://github.com/ParyaPayami/planarena-demo); PlanArena's full code is released with its paper.

## Esri UC 2027
The talk abstract, *Measure, Predict, Prove: Testable AI Decision Support for Urban Planning*, is in `docs/UC2027_Measure_Predict_Prove.pdf`.

## License
No license has been granted yet: the code is published for review, and all rights are reserved by the author (Parya Payami). A license will be added later. Data come from public sources listed in `catalog/` and are not redistributed here; download them with the scripts.
