"""Open each generated PBIR in PBI Desktop, check for errors, save screenshot.

PBI Desktop (Store app) blocks CLI path args for paths outside user folders.
Fix: stage both .Report AND .SemanticModel to Documents before launching.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pythoncom
from pywinauto import Desktop

PBI_EXE = Path(
    r"C:\Program Files\WindowsApps"
    r"\Microsoft.MicrosoftPowerBIDesktop_2.152.1279.0_x64__8wekyb3d8bbwe"
    r"\bin\PBIDesktop.exe"
)
SCREENSHOT_DIR = Path("output/test_screenshots")
STAGING_DIR = Path.home() / "Documents" / "TabToPbi_Test"
REPORTS = [
    "output/simple.Report",
    "output/simple_join.Report",
    "output/simple_join_calculated_line.Report",
    "output/Superstore.Report",
    "output/tabpbi.Report",
]
_ERROR_KEYWORDS = {"cannot", "failed", "error", "crash", "undefined", "unhandled", "unable", "denied"}


def stage_report(rpath: Path) -> Path:
    """Copy .Report and sibling .SemanticModel to staging dir. Return staged .Report path."""
    stem = rpath.name.replace(".Report", "")
    model_dir = rpath.parent / f"{stem}.SemanticModel"

    for src in [rpath, model_dir]:
        dst = STAGING_DIR / src.name
        if dst.exists():
            shutil.rmtree(dst)
        if src.exists():
            shutil.copytree(src, dst)

    return STAGING_DIR / rpath.name


def wait_for_main_window(timeout: int = 90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            wins = Desktop(backend="uia").windows(title_re=".*Power BI Desktop.*")
            if wins:
                return wins[0]
        except Exception:
            pass
        time.sleep(2)
    return None


def wait_for_title_change(timeout: int = 120):
    """Wait until PBI title bar is no longer 'Untitled'."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            wins = Desktop(backend="uia").windows(title_re=".*Power BI Desktop.*")
            for w in wins:
                if "untitled" not in w.window_text().lower():
                    return w
        except Exception:
            pass
        time.sleep(2)
    return None


def find_error_dialog():
    try:
        for win in Desktop(backend="uia").windows():
            text = win.window_text().lower()
            if any(kw in text for kw in _ERROR_KEYWORDS):
                return win.window_text()
    except Exception:
        pass
    return None


def kill_pbi(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    time.sleep(3)


def run():
    pythoncom.CoInitialize()
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for report_str in REPORTS:
        rpath = Path(report_str)
        stem = rpath.name.replace(".Report", "")

        if not rpath.exists():
            results.append((stem, "SKIP", "Report folder not found"))
            continue

        staged = stage_report(rpath)
        print(f"\nOpening {stem} from {staged}...")
        proc = subprocess.Popen([str(PBI_EXE), str(staged.resolve())])

        try:
            main_win = wait_for_main_window(timeout=60)
            if main_win is None:
                results.append((stem, "FAIL", "PBI Desktop window did not appear"))
                kill_pbi(proc)
                continue

            loaded_win = wait_for_title_change(timeout=120)
            time.sleep(5)

            error = find_error_dialog()

            shot_path = None
            try:
                win = loaded_win or main_win
                win.set_focus()
                time.sleep(1)
                img = win.capture_as_image()
                if img:
                    shot_path = SCREENSHOT_DIR / f"{stem}.png"
                    img.save(str(shot_path))
            except Exception as e:
                shot_path = f"screenshot failed: {e}"

            if error:
                results.append((stem, "FAIL", f"Error dialog: '{error}' | screenshot: {shot_path}"))
            else:
                results.append((stem, "PASS", f"screenshot: {shot_path}"))

        except Exception as e:
            results.append((stem, "FAIL", str(e)))
        finally:
            kill_pbi(proc)

    print("\n" + "=" * 60)
    print("PBI Desktop E2E Results")
    print("=" * 60)
    failed = 0
    for stem, status, detail in results:
        icon = "OK" if status == "PASS" else ("--" if status == "SKIP" else "FAIL")
        print(f"  [{icon}] {stem}: {detail}")
        if status == "FAIL":
            failed += 1
    print("=" * 60)
    print(f"{len(results)} workbooks tested, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    run()
