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
