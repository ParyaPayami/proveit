"""Proof: score PlanArena's 2020 redevelopment forecast in ArcGIS Pro against records it never saw.

Prediction: PlanArena's five-year redevelopment probability for 42,170 Manhattan lots,
features dated 2020 (tools/export_planarena_forecast.py). Baseline: the soft-site rule
of thumb (share of allowed floor area not yet built). Observed outcome: NYC DOB
certificates of occupancy for new buildings issued 2021-2025, an independent record
(PlanArena was trained and tested on MapPLUTO changes, not on certificates).
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUTS, PROJECT, WORK, log, work_gdb, write_json  # noqa: E402
import score_layer  # noqa: E402

import arcpy  # noqa: E402

PROJECT_GDB = Path.home() / "Documents" / "ArcGIS" / "Projects" / "ProveIt" / "ProveIt.gdb"
WINDOW = {"prediction_date": "2021-01-01", "start": "2021-01-01", "end": "2025-12-31"}
OUTCOME = {"source": "nyc_certificates_of_occupancy", "where": "job_type='NB'"} | WINDOW
# Two independent outcomes: construction started (first new-building permit) and completed (certificate of
# occupancy) on lots without a recent building at the cutoff (certificates lag starts by years).
OUTCOMES = {
    "started": {"source": "nyc_dob_now_job_filings", "where": "job_type='New Building'"} | WINDOW,
    "completed": {"source": "nyc_certificates_of_occupancy", "where": "job_type='NB'",
                  "prediction_where": "year_built_2020 < 2015"} | WINDOW,
}
MATCH = {"polygon_match": "nearest", "distance_m": 30, "match_key": ["bbl", "bbl"]}


def main() -> None:
    arcpy.env.overwriteOutput = True
    gdb = work_gdb("proof_planarena", fresh=True)
    local = WORK / "planarena_forecast_2020.geojson"
    shutil.copyfile(PROJECT / "data" / "planarena_forecast_2020.geojson", local)
    raw = arcpy.conversion.JSONToFeatures(str(local), f"{gdb}\\forecast_wgs", "POLYGON")[0]
    lots = arcpy.management.Project(raw, f"{gdb}\\planarena_forecast_2020", arcpy.SpatialReference(2263))[0]
    log(f"lots: {int(arcpy.management.GetCount(lots)[0]):,}")

    res = {}
    # Matching points inside lots first: the trap check should flag frontage geocoding.
    r = score_layer.run({"prediction": lots, "field": "p_redev_5yr", "outcome_as": "any", "polygon_match": "inside",
                         "name": "planarena_model_inside"} | OUTCOME)
    res["model_inside_match"] = {"headline": r["scorecard"]["headline"],
                                 "trap": next((t["detail"] for t in r["scorecard"]["traps"] if t["id"] == "records_beside_polygons"), None)}
    log(f"inside matching: {r['scorecard']['headline']}")
    for outcome, spec in OUTCOMES.items():
        for field, label in (("p_redev_5yr", "planarena_model"), ("soft_site", "soft_site_rule")):
            r = score_layer.run({"prediction": lots, "field": field, "outcome_as": "any",
                                 "name": f"planarena_{outcome}_{label}"} | MATCH | spec)
            res[f"{outcome}_{label}"] = {"headline": r["scorecard"]["headline"], "metrics": r["scorecard"]["metrics"],
                                         "traps": [(t["status"], t["id"]) for t in r["scorecard"]["traps"]],
                                         "layer": r["layer"]}
            log(f"{outcome} / {label}: {r['scorecard']['headline']}")
    # The earlier, unfair comparison kept for the record: all lots against all certificates.
    r = score_layer.run({"prediction": lots, "field": "p_redev_5yr", "outcome_as": "any",
                         "name": "planarena_completed_all_lots"} | MATCH | OUTCOME)
    res["completed_all_lots_planarena_model"] = {"headline": r["scorecard"]["headline"]}
    # Map-ready copy of the scored model layer in the Pro project.
    if arcpy.Exists(str(PROJECT_GDB)):
        arcpy.management.CopyFeatures(res["started_planarena_model"]["layer"], str(PROJECT_GDB / "planarena_forecast_scored"))
    write_json(OUTPUTS / "proof_planarena.json", res)


if __name__ == "__main__":
    main()
