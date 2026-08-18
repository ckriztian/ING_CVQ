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
                "assert main.MODELOS_PATH.is_file(); "
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
