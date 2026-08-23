# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the continuous sync runner.

Was previously untracked - .gitignore excluded *.spec, so the only copy lived on
whichever machine last ran the build. Committed now: this is a build input, not an
artifact.

configurations.json is deliberately NOT bundled. It is read from the working
directory at runtime so the production server keeps its own copy - see
app/core/config.py. build_exe.py copies the local one into dist/ for convenience;
do not overwrite production's with it.
"""

from PyInstaller.utils.hooks import collect_all

# gql and graphql-core resolve a fair amount at import time. Collect them whole
# rather than chasing individual submodules.
gql_datas, gql_binaries, gql_hidden = collect_all("gql")
graphql_datas, graphql_binaries, graphql_hidden = collect_all("graphql")

a = Analysis(
    ["continuous_main.py"],
    pathex=["."],
    binaries=gql_binaries + graphql_binaries,
    datas=gql_datas + graphql_datas,
    hiddenimports=gql_hidden + graphql_hidden + [
        "gql.transport.aiohttp",
        "gql.transport.exceptions",
        # Root-level module imported by app/sync/sales/orders_sync.py
        "order_location_mapper",
        # certifi backs the stable CA bundle app/utils/ssl_cert.py writes next to the exe
        "certifi",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide2"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ShopifySAPIntegration",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
