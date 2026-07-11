# -*- mode: python ; coding: utf-8 -*-
import os

spec_dir = os.path.dirname(os.path.abspath(SPEC)) if SPEC else os.path.dirname(__file__)

a = Analysis(
    [os.path.join(spec_dir, 'cli', 'demo.py')],
    pathex=[spec_dir],
    binaries=[],
    datas=[],
    hiddenimports=['common', 'common.api', 'questionary', 'prompt_toolkit', 'rich'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6'],
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
    name='算法体检工具_演示版',
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
