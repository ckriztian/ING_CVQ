import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "comparison.js"


def run_engine(expression):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js no está disponible")
    script = f"const E=require({json.dumps(str(ENGINE))}); console.log(JSON.stringify({expression}));"
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_numeric_delta_and_swapped_sign():
    assert run_engine("[E.numericDelta(28,34),E.numericDelta(34,28)]") == [6, -6]
    assert run_engine("E.numericDelta(null,34)") is None


def test_sector_alignment_is_safe_and_keeps_exclusive_sectors():
    expression = "E.alignPersonnel({tramos:[{nombre:' Desembalaje ',personas:12},{nombre:'Soldadura',personas:7}]},{tramos:[{nombre:'desembalaje',personas:14},{nombre:'Calesita soldadura',personas:8}]})"
    rows = run_engine(expression)
    by_key = {row["key"]: row for row in rows}
    assert by_key["desembalaje"]["delta"] == 2
    assert by_key["soldadura"]["b"] is None
    assert by_key["calesita soldadura"]["a"] is None
    assert len(rows) == 3


def test_personnel_missing_is_not_converted_to_zero():
    assert run_engine("E.totalPersonnel(null)") is None
    rows = run_engine("E.alignPersonnel({tramos:[{nombre:'A',personas:2}]},null)")
    assert rows[0]["a"] == 2
    assert rows[0]["b"] is None
    assert rows[0]["delta"] is None


def test_comparability_available_partial_warning_and_missing():
    a = "{data_status:{palletizacion:'available',specs:'available',personal:'available',layout:'missing',tiempos:'missing'}}"
    b = "{data_status:{palletizacion:'warning',specs:'missing',personal:'available',layout:'missing',tiempos:'available'}}"
    states = run_engine(f"E.dataComparability({a},{b})")
    assert states["palletizacion"]["state"] == "warning"
    assert states["specs"]["state"] == "partial"
    assert states["personal"]["state"] == "available"
    assert states["layout"]["state"] == "missing"
    assert states["tiempos"]["state"] == "partial"


@pytest.mark.parametrize("rows,expected", [
    ([{"nombre": "", "personas": 1}], "nombre"),
    ([{"nombre": "A", "personas": -1}], "cero"),
    ([{"nombre": "A", "personas": 1}, {"nombre": "a", "personas": 2}], "duplicado"),
])
def test_personnel_validation_rejects_invalid_rows(rows, expected):
    result = run_engine(f"E.validatePersonnelRows({json.dumps(rows)})")
    assert result["valid"] is False
    assert expected in result["error"]


def test_personnel_validation_accepts_empty_initial_or_valid_structure():
    assert run_engine("E.validatePersonnelRows([])")["valid"] is True
    assert run_engine("E.validatePersonnelRows([{nombre:'Vacío',personas:0}])")["valid"] is True
