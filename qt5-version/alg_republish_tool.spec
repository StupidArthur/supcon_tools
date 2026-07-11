# -*- mode: python ; coding: utf-8 -*-
import os

spec_dir = os.path.dirname(os.path.abspath(SPEC)) if SPEC else os.path.dirname(__file__)
src_dir = os.path.join(spec_dir, 'alg_republish')

a = Analysis(
    [os.path.join(src_dir, 'ui.py'),
     os.path.join(src_dir, 'api.py')],
    pathex=[src_dir],
    binaries=[],
    datas=[],
    hiddenimports=['PyQt5', 'httpx', 'api'],
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
    name='算法重发布工具_低系统版本',
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
