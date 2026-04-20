"""UI integration tests for PBI Desktop — Layer 1 (open) + Layer 3A (visual type)."""

import json
import subprocess
import time
from pathlib import Path

import pytest
from pywinauto import Desktop
from pywinauto.application import Application

PBI_EXE = Path(
    r"C:\Program Files\WindowsApps"
    r"\Microsoft.MicrosoftPowerBIDesktop_2.152.1279.0_x64__8wekyb3d8bbwe"
    r"\bin\PBIDesktop.exe"
)
REPORT_DIR = Path("output/simple.Report")
TRANSFORMED_JSON = Path("output/simple.transformed.json")
SCREENSHOT_DIR = Path("output/test_screenshots")

# Titles that indicate a fatal error dialog from PBI Desktop
_ERROR_TITLES = {"Error", "Microsoft Power BI Desktop", "Warning"}
_ERROR_KEYWORDS = {"cannot", "failed", "error", "crash", "undefined"}


def _launch_pbi(report_path: Path) -> subprocess.Popen:
    """Launch PBI Desktop with the given report folder."""
    return subprocess.Popen([str(PBI_EXE), str(report_path.resolve())])


def _wait_for_main_window(timeout: int = 60):
    """Wait until the PBI Desktop main window appears."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        wins = Desktop(backend="uia").windows(title_re=".*Power BI Desktop.*")
        if wins:
            return wins[0]
        time.sleep(2)
    raise TimeoutError("PBI Desktop main window did not appear within timeout")


def _find_error_dialog():
    """Return an error dialog window if one is visible, else None."""
    for win in Desktop(backend="uia").windows():
        title = win.window_text()
        text = title.lower()
        if any(kw in text for kw in _ERROR_KEYWORDS):
            return win
    return None


def _screenshot(win, filename: str):
    """Save a screenshot of the window; silently skips if PIL unavailable."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    img = win.capture_as_image()
    if img:
        img.save(str(SCREENSHOT_DIR / filename))


def _kill_pbi(proc: subprocess.Popen):
    """Terminate all PBI Desktop processes."""
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def pbi_session():
    """Launch PBI Desktop for the test module, yield main window, then close."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    proc = _launch_pbi(REPORT_DIR)
    try:
        main_win = _wait_for_main_window(timeout=60)
        time.sleep(5)  # allow report and visuals to fully render
        yield main_win
    finally:
        _kill_pbi(proc)


# ---------------------------------------------------------------------------
# Layer 1 — opens without errors
# ---------------------------------------------------------------------------

def test_pbi_opens_without_error(pbi_session):
    """PBI Desktop main window appears and no error dialog is shown."""
    assert pbi_session is not None, "Main window not found"

    error = _find_error_dialog()
    if error:
        _screenshot(pbi_session, "error_dialog.png")
        pytest.fail(f"Error dialog detected: '{error.window_text()}'")


def test_pbi_screenshot_saved(pbi_session):
    """Save a screenshot of the loaded report for human review."""
    _screenshot(pbi_session, "simple_report.png")
    img_path = SCREENSHOT_DIR / "simple_report.png"
    assert img_path.exists(), "Screenshot was not saved"
    print(f"\nScreenshot: {img_path}")


# ---------------------------------------------------------------------------
# Layer 3 — correct visual type in generated PBIR files
#
# PBI Desktop renders visuals inside a WebView (Chromium), so visual types
# are not exposed in the native UIA accessibility tree. We validate the
# visualType written to visual.json by the pipeline instead, which is the
# authoritative source before PBI Desktop interprets it.
# ---------------------------------------------------------------------------

_MARK_TO_VISUAL = {
    "Bar": "barChart", "Column": "columnChart",
    "Line": "lineChart", "Text": "tableEx", "Automatic": "tableEx",
}


def test_visual_types_in_generated_files(pbi_session):
    """Assert visual.json files contain the correct visualType per sheet.

    Also saves a screenshot for human review of the rendered result.
    """
    _screenshot(pbi_session, "simple_report_visual_check.png")

    transformed = json.loads(TRANSFORMED_JSON.read_text())
    pages_dir = REPORT_DIR / "definition" / "pages"

    for i, visual_info in enumerate(transformed.get("visuals", [])):
        expected_type = _MARK_TO_VISUAL.get(visual_info["mark_type"], "tableEx")
        section = f"ReportSection{i + 1}"
        visual_json = pages_dir / section / "visuals" / f"visual_{i + 1}" / "visual.json"

        assert visual_json.exists(), f"visual.json missing for {section}"
        content = json.loads(visual_json.read_text())
        actual_type = content["visual"]["visualType"]
        assert actual_type == expected_type, (
            f"Sheet '{visual_info['name']}': expected visualType '{expected_type}', "
            f"got '{actual_type}'"
        )
