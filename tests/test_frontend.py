import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"


def inline_javascript() -> str:
    html = INDEX.read_text(encoding="utf-8")
    return "\n".join(re.findall(r"<script(?: [^>]*)?>(.*?)</script>", html, re.DOTALL))


def test_frontend_javascript_syntax(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js no está disponible")
    script = tmp_path / "index-inline.js"
    script.write_text(inline_javascript(), encoding="utf-8")
    subprocess.run([node, "--check", str(script)], check=True, capture_output=True, text=True)


def test_active_model_state_is_global_and_contains_no_secret_storage():
    script = inline_javascript()
    assert "let activeModel = null" in script
    assert "sessionStorage.setItem('ACTIVE_MODEL_ID'" in script
    assert "restoreActiveModel()" in script
    assert "syncSelections(identity)" in script
    assert "localStorage" not in script


def test_home_and_model_navigation_are_present():
    html = INDEX.read_text(encoding="utf-8")
    assert 'class="page active" id="page-home"' in html
    assert 'data-page="home"' in html
    assert 'data-page="ficha"' in html
    assert "Centro de ingeniería de producto" in html
    assert "openActivePage('specs')" in html
    assert "openActivePage('pallets')" in html
    assert "openActivePage('personal')" in html
    assert "openActivePage('layouts')" in html
    assert "openActivePage('tiempos')" in html
    assert '<link rel="stylesheet" href="styles.css">' in html
    assert "<style>" not in html


def test_quick_selector_only_uses_master_model_catalog():
    script = inline_javascript()
    assert "populateQuickModelSearch()" in script
    assert "function selectQuickModel()" in script
    assert "MASTER_MODELS.filter" in script
    assert "item.sku_bgh" in script
    assert "item.pnb" in script


def test_missing_and_warning_states_have_textual_labels():
    script = inline_javascript()
    for label in ["Disponible", "Advertencia", "Faltante", "Sin datos de dotación", "Sin especificaciones"]:
        assert label in script
    assert "Requiere validación de Ingeniería/Logística" in script
    assert "Fecha pendiente de validación" in script


def test_engineering_views_include_times_table_and_integrity_panel():
    html = INDEX.read_text(encoding="utf-8")
    script = inline_javascript()
    assert 'id="tiempos-table-body"' in html
    assert "function renderTiemposTable" in script
    assert "Dentro de ciclo" in script
    assert "Próximo al límite" in script
    assert "Sobre ciclo" in script
    assert 'id="integrity-panel"' in html
    assert "function loadIntegrityPanel" in script
