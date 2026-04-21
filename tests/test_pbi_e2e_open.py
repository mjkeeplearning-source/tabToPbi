"""E2E UI tests: open each generated PBIR in PBI Desktop and check for errors."""

import subprocess
import time
from pathlib import Path

import pytest
from pywinauto import Desktop

PBI_EXE = Path(
    r"C:\Program Files\WindowsApps"
    r"\Microsoft.MicrosoftPowerBIDesktop_2.152.1279.0_x64__8wekyb3d8bbwe"
    r"\bin\PBIDesktop.exe"
)
SCREENSHOT_DIR = Path("output/test_screenshots")

ALL_REPORTS = [
    "output/simple.Report",
    "output/simple_join.Report",
    "output/simple_join_calculated_line.Report",
    "output/Superstore.Report",
    "output/tabpbi.Report",
]

_ERROR_KEYWORDS = {"cannot", "failed", "error", "crash", "undefined", "unhandled"}


def _launch_pbi(report_path: Path) -> subprocess.Popen:
    return subprocess.Popen([str(PBI_EXE), str(report_path.resolve())])


def _wait_for_main_window(timeout: int = 90) -> object:
    deadline = time.time() + timeout
    while time.time() < deadline:
        wins = Desktop(backend="uia").windows(title_re=".*Power BI Desktop.*")
        if wins:
            return wins[0]
        time.sleep(2)
    raise TimeoutError("PBI Desktop main window did not appear within timeout")


def _find_error_dialog():
    for win in Desktop(backend="uia").windows():
        text = win.window_text().lower()
        if any(kw in text for kw in _ERROR_KEYWORDS):
            return win
    return None


def _screenshot(win, stem: str, label: str):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    img = win.capture_as_image()
    if img:
        path = SCREENSHOT_DIR / f"{stem}_{label}.png"
        img.save(str(path))
        return path
    return None


def _kill_pbi(proc: subprocess.Popen):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    time.sleep(2)  # allow process to fully exit before next launch


@pytest.mark.parametrize("report_dir", ALL_REPORTS)
def test_report_opens_without_error(report_dir):
    """Open each PBIR in PBI Desktop and assert no error dialog appears."""
    rpath = Path(report_dir)
    stem = rpath.stem.replace(".Report", "")

    assert rpath.exists(), f"Report folder not found: {rpath}"

    proc = _launch_pbi(rpath)
    try:
        main_win = _wait_for_main_window(timeout=90)
        time.sleep(8)  # allow report and visuals to fully render

        error = _find_error_dialog()
        shot = _screenshot(main_win, stem, "open")

        if error:
            _screenshot(main_win, stem, "error")
            pytest.fail(
                f"[{stem}] Error dialog detected: '{error.window_text()}' "
                f"— screenshot: {shot}"
            )

        print(f"\n[{stem}] OK — screenshot: {shot}")
    finally:
        _kill_pbi(proc)
