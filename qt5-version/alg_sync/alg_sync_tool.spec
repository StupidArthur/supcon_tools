# -*- mode: python ; coding: utf-8 -*-
import os

spec_dir = os.path.dirname(os.path.abspath(SPEC)) if SPEC else os.path.dirname(__file__)
src_dir = spec_dir

a = Analysis(
    [os.path.join(src_dir, 'ui.py')],
    pathex=[spec_dir, '..'],
    binaries=[],
    datas=[],
    hiddenimports=['PyQt5', 'httpx'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='算法同步工具_低系统版本',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
