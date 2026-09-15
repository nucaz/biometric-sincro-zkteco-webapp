# PyInstaller spec for the ZKTeco Attendance System desktop GUI.
# Build with:  pyinstaller deploy/windows_desktop/attendance_gui.spec
# (run from the project root so relative paths below resolve correctly)
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), "..", ".."))

datas = []
datas += collect_data_files("tkcalendar")
datas += collect_data_files("babel")  # locale data tkcalendar needs at runtime

hiddenimports = []
hiddenimports += collect_submodules("babel")

a = Analysis(
    [os.path.join(PROJECT_ROOT, "attendance_gui.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ZKTecoAttendanceSystem",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_ROOT, "deploy", "windows_desktop", "app.ico")
        if os.path.exists(os.path.join(PROJECT_ROOT, "deploy", "windows_desktop", "app.ico")) else None,
    version=os.path.join(PROJECT_ROOT, "deploy", "windows_desktop", "version_info.txt")
        if os.path.exists(os.path.join(PROJECT_ROOT, "deploy", "windows_desktop", "version_info.txt")) else None,
)
