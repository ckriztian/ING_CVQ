"""Diagnóstico no destructivo del backend Excel COM para Windows."""

import platform
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from work_instruction_exporter import ExcelComWorkInstructionExporter  # noqa: E402


def report(label: str, ok: bool, detail: str = "") -> None:
    print(f"{label}: {'OK' if ok else 'ERROR'}" + (f" — {detail}" if detail else ""))


def main() -> int:
    is_windows = platform.system() == "Windows"
    report("Windows", is_windows, platform.system())
    try:
        import win32com.client  # noqa: F401
        pywin32_ok, pywin32_detail = True, "win32com.client importado"
    except ImportError as exc:
        pywin32_ok, pywin32_detail = False, str(exc)
    report("pywin32", pywin32_ok, pywin32_detail)

    template = ROOT / "templates" / "it" / "BSIP_IT_template.xlsx"
    report("Template", template.is_file(), str(template))
    exporter = ExcelComWorkInstructionExporter(template, ROOT / "data" / "work_instructions")
    if is_windows and pywin32_ok:
        excel_ok, excel_detail = exporter.availability()
    else:
        excel_ok, excel_detail = False, "prueba omitida por prerrequisitos"
    report("Excel COM", excel_ok, excel_detail)
    return 0 if all((is_windows, pywin32_ok, template.is_file(), excel_ok)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
