# -*- mode: python ; coding: utf-8 -*-

import os
import sys


def _conda_binaries(*names: str):
    """将当前 Python 环境（conda）Library/bin 下的运行时 DLL 一并打包。

    Windows conda 发行版中，``_ctypes.pyd`` / ``_sqlite3.pyd`` 等标准库
    扩展链接的 DLL（ffi-8.dll、sqlite3.dll、openssl 等）位于
    ``<env>/Library/bin/`` 而非 ``DLLs/`` 目录，PyInstaller 依赖分析
    可能漏收集，运行时报 ``DLL load failed``。此处按 ``sys.prefix``
    显式收集，缺失的 DLL 自动跳过（如 python.org 发行版自带这些 DLL）。
    """
    result = []
    for name in names:
        path = os.path.join(sys.prefix, "Library", "bin", name)
        if os.path.exists(path):
            result.append((path, "."))
    return result


a = Analysis(
    ['sidecar_launcher.py'],
    pathex=[],
    binaries=_conda_binaries(
        'ffi-8.dll',
        'sqlite3.dll',
        'libcrypto-3-x64.dll',
        'libssl-3-x64.dll',
        'libbz2.dll',
        'liblzma.dll',
        'libexpat.dll',
    ),
    datas=[('backend', 'backend'), ('app', 'app'), ('crawlers', 'crawlers'), ('downloader', 'downloader')],
    hiddenimports=['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.websockets.auto', 'uvicorn.protocols.websockets.wsproto_impl', 'uvicorn.lifespan.on', 'starlette.middleware.cors', 'databases', 'sqlalchemy', 'httpx', 'httpcore', 'anyio', 'sniffio', 'curl_cffi', 'curl_cffi.requests', 'curl_cffi.requests.exceptions'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt5', 'PySide6', 'matplotlib', 'numpy', 'pandas'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='backend-sidecar',
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
