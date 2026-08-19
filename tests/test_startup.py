import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_data_paths_include_master_catalog():
    import main

    assert main.MODELOS_PATH == ROOT / "modelos.json"
    assert main.MODELOS_PATH.is_file()
    assert len(main.MODELOS) == 20


def test_startup_load_does_not_depend_on_modelos_path_alias():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "MODELOS = load_models(MODELOS_PATH)" not in source
    assert 'MODELOS = load_models(BASE_DIR / "modelos.json")' in source


def test_fresh_process_imports_app_from_external_working_directory(tmp_path):
    """Reproduce la importación realizada por el subproceso de Uvicorn --reload."""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import main; "
                "assert (main.BASE_DIR / 'modelos.json').is_file(); "
                "assert len(main.MODELOS) == 20; "
                "assert main.app.title.startswith('BGH')"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
