"""ProveIt toolbox: score any GIS or AI prediction against public records of what really happened.

Tools
  Find Truth Sources   which public outcome records cover my area and topic?
  Get Truth Records    download them for a study area and dates
  Score My Layer       score a prediction layer against them, with a trap check
  Proof cases          the reference cases that show the scoring is right
"""

import importlib
import json
import sys
from pathlib import Path

import arcpy

PRO_DIR = Path(__file__).resolve().parent
PROJECT = PRO_DIR.parent
for p in (str(PRO_DIR), str(PROJECT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from proveit import truth  # noqa: E402

AUTOMATIC = [s["id"] for s in truth.sources() if s["adapter"]["type"] != "manual"]
TOPICS = sorted({t for s in truth.sources() for t in s.get("topics", [])})


def _param(name, label, datatype, required=True, direction="Input", default=None, values=None, category=None):
    p = arcpy.Parameter(displayName=label, name=name, datatype=datatype,
                        parameterType="Required" if required else "Optional", direction=direction, category=category)
    if values:
        p.filter.type = "ValueList"
        p.filter.list = values
    if default is not None:
        p.value = default
    return p


def _iso(param) -> str | None:
    return param.value.date().isoformat() if param.value else None


def _bbox(extent_param) -> list[float] | None:
    if not extent_param.value:
        return None
    e = extent_param.value
    sr = e.spatialReference or arcpy.SpatialReference(4326)
    poly = arcpy.Polygon(arcpy.Array([arcpy.Point(e.XMin, e.YMin), arcpy.Point(e.XMax, e.YMax),
                                      arcpy.Point(e.XMin, e.YMax)]), sr).projectAs(arcpy.SpatialReference(4326)).extent
    return [poly.XMin, poly.YMin, poly.XMax, poly.YMax]


class Toolbox:
    def __init__(self):
        self.label = "ProveIt"
        self.alias = "proveit"
        self.tools = [FindTruthSources, GetTruthRecords, ScoreMyLayer, FireCoverage, FloodLowSpots, WildfireExposure, ScoreCase]


class FindTruthSources:
    label = "1. Find Truth Sources"
    description = "Lists public records of real outcomes (permits, response times, flood marks, inspections, sensors) that cover an area and topic."
    canRunInBackground = False

    def getParameterInfo(self):
        return [_param("area", "Area of interest", "GPExtent", required=False),
                _param("topic", "Topic", "GPString", required=False, values=TOPICS),
                _param("text", "Search words", "GPString", required=False)]

    def execute(self, parameters, messages):
        found = truth.find(_bbox(parameters[0]), parameters[1].valueAsText or "", parameters[2].valueAsText or "")
        messages.addMessage(f"{len(found)} truth sources:")
        for s in found:
            mode = "manual download" if s["adapter"]["type"] == "manual" else "automatic"
            messages.addMessage(f"\n{s['id']}  ({s['outcome']['kind']}, {mode})\n  {s['name']}\n  {s['outcome']['describes']}"
                                f"\n  Coverage: {s['coverage'].get('place')} from {s['coverage'].get('start', '?')}"
                                + (f"\n  Filter example: {s['filters_example']}" if s.get("filters_example") else "")
                                + "".join(f"\n  Trap: {t['check']}" for t in s.get("traps", [])))


class GetTruthRecords:
    label = "2. Get Truth Records"
    description = "Downloads a truth source for a study area and date range into a feature class, recording source and fingerprint."
    canRunInBackground = False

    def getParameterInfo(self):
        return [_param("source", "Truth source", "GPString", values=AUTOMATIC),
                _param("area", "Study area", "GPExtent", required=False),
                _param("start", "From date", "GPDate", required=False),
                _param("end", "To date", "GPDate", required=False),
                _param("where", "Filter (source fields)", "GPString", required=False),
                _param("out", "Output feature class", "DEFeatureClass", direction="Output")]

    def execute(self, parameters, messages):
        p = parameters
        path, meta = truth.get(p[0].valueAsText, _bbox(p[1]), _iso(p[2]), _iso(p[3]), p[4].valueAsText)
        if meta["format"] == "areal_json":
            raise arcpy.ExecuteError("This source is published as area totals; use it directly in Score My Layer with a key field.")
        local = Path(arcpy.env.scratchFolder) / "truth.geojson"
        local.write_bytes(path.read_bytes())
        gj = json.loads(local.read_text())
        gtype = next((f["geometry"]["type"] for f in gj["features"] if f.get("geometry")), "Point")
        arcpy.conversion.JSONToFeatures(str(local), p[5].valueAsText, "POLYGON" if "Polygon" in gtype else "POINT")
        messages.addMessage(f"{meta['records']:,} records from {meta['source_name']} (SHA-256 {meta['sha256'][:12]}...)")
        if meta.get("truncated"):
            messages.addWarningMessage("Row limit reached: narrow the area, dates or filter.")


class ScoreMyLayer:
    label = "3. Score My Layer"
    description = ("Scores any prediction (points, polygons or raster) against a truth source: matches places and dates, "
                   "picks the right test, checks known traps, and writes a scorecard, report and a map of where the model was wrong.")
    canRunInBackground = False

    def getParameterInfo(self):
        pred = _param("prediction", "Prediction layer", ["GPFeatureLayer", "GPRasterLayer"])
        field = _param("field", "Prediction field", "Field", required=False)
        field.parameterDependencies = [pred.name]
        key = _param("key_field", "Area code field (for sources published by area)", "Field", required=False, category="Matching")
        key.parameterDependencies = [pred.name]
        out = _param("scored", "Scored layer", "DEFeatureClass", required=False, direction="Output")
        return [pred, field,
                _param("higher_means", "Higher prediction means", "GPString", default="more of the outcome",
                       values=["more of the outcome", "less of the outcome"]),
                _param("source", "Truth source", "GPString", values=AUTOMATIC),
                _param("prediction_date", "Prediction made on", "GPDate", required=False),
                _param("start", "Outcomes from", "GPDate", required=False),
                _param("end", "Outcomes to", "GPDate", required=False),
                _param("where", "Filter (source fields)", "GPString", required=False),
                _param("distance_m", "Match distance for points (m)", "GPDouble", required=False, default=30, category="Matching"),
                key,
                _param("min_records", "Minimum records per feature", "GPLong", required=False, default=1, category="Matching"),
                _param("same_units", "Prediction is in the outcome's units", "GPBoolean", required=False, default=False, category="Matching"),
                _param("tolerance", "Tolerance (outcome units)", "GPDouble", required=False, category="Matching"),
                _param("name", "Run name", "GPString", default="my_layer"),
                out]

    def updateMessages(self, parameters):
        if parameters[3].value and not parameters[6].value and parameters[4].value:
            parameters[5].setWarningMessage("Set 'Outcomes from' on or after the prediction date to avoid scoring hindsight.")

    def execute(self, parameters, messages):
        p = {x.name: x for x in parameters}
        score_layer = importlib.reload(importlib.import_module("score_layer"))
        cfg = {"prediction": p["prediction"].valueAsText, "field": p["field"].valueAsText,
               "higher_means": "less" if (p["higher_means"].valueAsText or "").startswith("less") else "more",
               "source": p["source"].valueAsText, "prediction_date": _iso(p["prediction_date"]),
               "start": _iso(p["start"]), "end": _iso(p["end"]), "where": p["where"].valueAsText,
               "distance_m": p["distance_m"].value or 30, "key_field": p["key_field"].valueAsText,
               "min_records": p["min_records"].value or 1, "same_units": bool(p["same_units"].value),
               "tolerance": p["tolerance"].value, "name": p["name"].valueAsText}
        res = score_layer.run(cfg)
        card = res["scorecard"]
        messages.addMessage(card["headline"])
        for t in card["traps"]:
            (messages.addWarningMessage if t["status"] == "warning" else messages.addMessage)(f"[{t['status']}] {t['id']}: {t['detail']}")
        messages.addMessage(f"Report: {Path(res['out_dir']) / 'report.html'}")
        if res["layer"]:
            wanted = parameters[-1].valueAsText
            if wanted:
                arcpy.management.CopyFeatures(res["layer"], wanted)
            parameters[-1].value = wanted or res["layer"]


class _CaseTool:
    module = ""
    case = ""
    canRunInBackground = False
    category = "Proof cases"

    def getParameterInfo(self):
        return []

    def execute(self, parameters, messages):
        mod = importlib.reload(importlib.import_module(self.module))
        mod.main()
        messages.addMessage(f"Done. Outputs in {PROJECT / 'outputs' / self.case}. Score with the Score Case tool.")


class FireCoverage(_CaseTool):
    label = "Fire Coverage vs Observed Travel Times (NYC)"
    description = ("Builds a drive-time network from street centerlines and compares nearest-firehouse drive time with FDNY's "
                   "recorded travel times by ZIP area. Optionally limit the scored areas by ZIP prefix (e.g. 112 = Brooklyn); "
                   "the network and firehouses stay citywide.")
    module, case = "fire_ems", "fire_ems"

    def getParameterInfo(self):
        return [_param("area_prefix", "Study area: ZIP area prefix (e.g. 112 for Brooklyn)", "GPString", required=False)]

    def execute(self, parameters, messages):
        mod = importlib.reload(importlib.import_module(self.module))
        prefix = parameters[0].valueAsText
        mod.main(prefix)
        name = f"fire_ems_{prefix}" if prefix else "fire_ems"
        messages.addMessage(f"Done. Outputs in {PROJECT / 'outputs' / name}. Score with: python3 -m proveit.score fire_ems {name}")


class FloodLowSpots(_CaseTool):
    label = "Flood Low Spots vs Ida High-Water Marks (NYC)"
    description = "Finds terrain low spots in USGS 3DEP elevation and tests them against USGS high-water marks and control points."
    module, case = "flood_ida", "flood_ida"


class WildfireExposure(_CaseTool):
    label = "Wildfire Exposure vs Damage Inspections (LA 2025)"
    description = "Computes pre-fire structure features and tests them against CAL FIRE damage inspections, excluding uninspected structures."
    module, case = "wildfire_la", "wildfire_la"


class ScoreCase:
    label = "Score Proof Case"
    description = "Independent scorer for the proof cases."
    canRunInBackground = False
    category = "Proof cases"

    def getParameterInfo(self):
        return [_param("case", "Case", "GPString", values=["fire_ems", "flood_ida", "wildfire_la"])]

    def execute(self, parameters, messages):
        score = importlib.reload(importlib.import_module("proveit.score"))
        messages.addMessage(json.dumps(score.main(parameters[0].valueAsText), indent=2))
