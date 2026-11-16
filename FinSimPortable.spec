# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
datas += collect_data_files(
    'matplotlib',
    includes=[
        'mpl-data/matplotlibrc',
        'mpl-data/fonts/ttf/DejaVuSans.ttf',
        'mpl-data/fonts/ttf/DejaVuSans-Bold.ttf',
        'mpl-data/fonts/ttf/DejaVuSans-Oblique.ttf',
        'mpl-data/fonts/ttf/DejaVuSans-BoldOblique.ttf',
        'mpl-data/fonts/ttf/LastResortHE-Regular.ttf',
        'mpl-data/fonts/ttf/LICENSE_DEJAVU',
    ],
)
tmp_ret = collect_all('yfinance')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
tmp_ret = collect_all('curl_cffi')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

excluded_modules = [
    'PySide6.QtOpenGL',
    'PySide6.QtPdf',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtVirtualKeyboard',
]
optional_qt_binaries = {
    'opengl32sw.dll',
    'qt6opengl.dll',
    'qt6pdf.dll',
    'qt6qml.dll',
    'qt6qmlmeta.dll',
    'qt6qmlmodels.dll',
    'qt6qmlworkerscript.dll',
    'qt6quick.dll',
    'qt6virtualkeyboard.dll',
}
matplotlib_data_files = {
    'matplotlib/mpl-data/matplotlibrc',
    'matplotlib/mpl-data/fonts/ttf/dejavusans.ttf',
    'matplotlib/mpl-data/fonts/ttf/dejavusans-bold.ttf',
    'matplotlib/mpl-data/fonts/ttf/dejavusans-oblique.ttf',
    'matplotlib/mpl-data/fonts/ttf/dejavusans-boldoblique.ttf',
    'matplotlib/mpl-data/fonts/ttf/lastresorthe-regular.ttf',
    'matplotlib/mpl-data/fonts/ttf/license_dejavu',
}


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)
a.binaries = [
    entry for entry in a.binaries if Path(entry[0]).name.lower() not in optional_qt_binaries
]
a.datas = [
    entry
    for entry in a.datas
    if '/translations/' not in f"/{entry[0].replace(chr(92), '/').lower()}"
    and (
        not entry[0].replace(chr(92), '/').lower().startswith('matplotlib/mpl-data/')
        or entry[0].replace(chr(92), '/').lower() in matplotlib_data_files
    )
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FinSimPortable',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FinSimPortable',
)
