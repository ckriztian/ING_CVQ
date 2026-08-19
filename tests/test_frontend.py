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


def test_comparator_is_public_and_uses_two_model_summaries():
    html = INDEX.read_text(encoding="utf-8")
    script = inline_javascript()
    assert 'data-page="compare"' in html
    assert 'id="compare-a"' in html and 'id="compare-b"' in html
    assert "idA === idB" in script
    assert "Promise.all([api(`/modelos/${encodeURIComponent(idA)}/resumen`)" in script
    assert "X-API-Key" not in script[script.index("// COMPARADOR DE MODELOS"):script.index("/* ── Alert helper")]
    assert "swapComparedModels" in script
    assert "applyComparisonFilter" in script


def test_personnel_defaults_to_read_only_and_edit_requires_memory_key():
    script = inline_javascript()
    read_block = script[script.index("function renderPersonalRead"):script.index("function enterPersonalEdit")]
    assert '<table class="technical-table staff-table">' in read_block
    assert "<input" not in read_block
    assert "getAdminKey()" in read_block
    assert "function enterPersonalEdit" in script
    assert "if (!getAdminKey()) return" in script
    assert "MODO EDICIÓN" in script
    assert "cancelPersonalEdit" in script


def test_personnel_save_reloads_read_view_and_unsaved_changes_are_guarded():
    script = inline_javascript()
    assert "ComparisonEngine.validatePersonnelRows(PERSONAL_DATA)" in script
    assert "await loadPersonal()" in script
    assert "Dotación actualizada correctamente" in script
    assert "Hay cambios de dotación sin guardar" in script
    assert "localStorage" not in script
