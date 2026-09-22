"""Frozen, shared fixed-2/4/8 observation sequences for the current datasets."""
import json
from pathlib import Path
FIXED_METHOD_BUDGETS = {"fixed experimental design (%d observations)" % b: b for b in (2, 4, 8)}
FIXED_DESIGN_MANIFEST = json.loads((Path(__file__).resolve().parents[2] / "datasets/fixed_budget_design.json").read_text())
FIXED_CONDITIONS = {name: tuple(value["conditions"]) for name, value in FIXED_DESIGN_MANIFEST["families"].items()}
