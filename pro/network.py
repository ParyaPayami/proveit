"""Build a Network Analyst network dataset with a travel-time cost from plain line data.

ArcPy can create a network dataset but only with a Length cost. We create that,
export its XML template, add a `Minutes` cost read from FT_Min / TF_Min fields
(negative values mean "cannot travel this way", which handles one-way
streets), then rebuild the network from the edited template.
"""

from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import arcpy

XSI = "http://www.w3.org/2001/XMLSchema-instance"
FIELD_SCRIPT = "{68055FC4-37D5-4BD0-81A5-CD177A29759C}"


def add_minutes_cost(template_xml: str, source: str, ft_field: str, tf_field: str,
                     elevation_fields: tuple[str, str] | None = None) -> None:
    """Add a `Minutes` cost (and optional elevation fields) to a network template, in place."""
    original = Path(template_xml).read_text(encoding="utf-8")
    # xsi:type values like "typens:..." need prefix declarations that
    # ElementTree drops as unused, so the original root tag is restored below.
    root_tag = original[: original.index(">") + 1]
    ET.register_namespace("xsi", XSI)
    root = ET.fromstring(original)

    attrs = root.find("EvaluatedNetworkAttributes")
    length = next(a for a in attrs if a.findtext("Name") == "Length")
    minutes = copy.deepcopy(length)
    minutes.find("ID").text = str(max(int(a.findtext("ID")) for a in attrs) + 1)
    minutes.find("Name").text = "Minutes"
    minutes.find("Units").text = "Minutes"
    minutes.find("UseByDefault").text = "true"
    attrs.append(minutes)

    assigns = root.find("NetworkAssignments")
    for a in list(assigns):
        if a.findtext("NetworkAttributeName") != "Length":
            continue
        new = copy.deepcopy(a)
        new.find("NetworkAttributeName").text = "Minutes"
        if new.findtext("NetworkEvaluatorCLSID") == FIELD_SCRIPT and new.findtext("NetworkSourceName") == source:
            along = new.findtext("NetworkEdgeDirection") == "esriNEDAlongDigitized"
            for prop in new.iter("PropertySetProperty"):
                if prop.findtext("Key") == "Expression":
                    prop.find("Value").text = f"!{ft_field if along else tf_field}!"
        assigns.append(new)

    if elevation_fields:
        # Edges connect only where their end levels match, so a street does not
        # join the highway that crosses over it.
        src = next(e for e in root.find("EdgeFeatureSources") if e.findtext("Name") == source)
        src.find("FromElevationFieldName").text, src.find("ToElevationFieldName").text = elevation_fields
        root.find("NetworkElevationModel").text = "1"

    _set_travel_modes(root, [TRAVEL_MODE])
    text = ET.tostring(root, encoding="unicode")
    text = root_tag + text[text.index(">") + 1 :]
    Path(template_xml).write_text(text, encoding="utf-8")


TRAVEL_MODE = {
    "name": "Drive",
    "type": "AUTOMOBILE",
    "description": "Minutes from the Minutes cost; one-way streets respected.",
    "impedanceAttributeName": "Minutes",
    "timeAttributeName": "Minutes",
    "distanceAttributeName": "Length",
    "restrictionAttributeNames": [],
    "attributeParameterValues": [],
    "useHierarchy": False,
    "uturnAtJunctions": "esriNFSBAllowBacktrack",
    "simplificationTolerance": None,
    "simplificationToleranceUnits": "esriFeet",
}


def _prop(parent, key: str, value_type: str):
    p = ET.SubElement(parent, "PropertySetProperty", {f"{{{XSI}}}type": "typens:PropertySetProperty"})
    ET.SubElement(p, "Key").text = key
    return ET.SubElement(p, "Value", {f"{{{XSI}}}type": value_type})


def _set_travel_modes(root, modes: list[dict]) -> None:
    """Store travel modes the way Pro does: JSON strings in the root PropertySet."""
    props = root.find("Properties")
    props.attrib.clear()
    props.set(f"{{{XSI}}}type", "typens:PropertySet")
    arr = ET.SubElement(props, "PropertyArray", {f"{{{XSI}}}type": "typens:ArrayOfPropertySetProperty"})
    tm = _prop(arr, "NetworkTravelModes", "typens:PropertySet")
    tm_arr = ET.SubElement(tm, "PropertyArray", {f"{{{XSI}}}type": "typens:ArrayOfPropertySetProperty"})
    _prop(tm_arr, "TravelModeCount", "xs:int").text = str(len(modes))
    for i, mode in enumerate(modes):
        _prop(tm_arr, f"TravelMode{i}", "xs:string").text = json.dumps(mode)


def build_network(feature_dataset: str, source: str, name: str, ft_field: str, tf_field: str,
                  template_dir: Path, elevation_fields: tuple[str, str] | None = None) -> str:
    """Create, re-template with a Minutes cost, and build a network dataset."""
    arcpy.CheckOutExtension("Network")
    nd = f"{feature_dataset}\\{name}"
    if arcpy.Exists(nd):
        arcpy.management.Delete(nd)
    arcpy.na.CreateNetworkDataset(feature_dataset, name, [source], "NO_ELEVATION")
    template_dir.mkdir(parents=True, exist_ok=True)
    xml = str(template_dir / f"{name}_template.xml")
    arcpy.na.CreateTemplateFromNetworkDataset(nd, xml)
    arcpy.management.Delete(nd)
    add_minutes_cost(xml, source, ft_field, tf_field, elevation_fields)
    arcpy.na.CreateNetworkDatasetFromTemplate(xml, feature_dataset)
    arcpy.na.BuildNetwork(nd)
    return nd
