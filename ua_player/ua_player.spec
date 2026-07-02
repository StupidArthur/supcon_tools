# PyInstaller spec for OPC UA Data Player（单文件，尽量自带解释器与依赖）
# 在 ua_player 目录下执行: pyinstaller ua_player.spec
#
# 说明：
# - asyncua / cryptography 含动态导入与随包数据（证书等），仅靠少量 hiddenimports 容易在目标机报缺模块。
# - 使用 collect_all 把上述包的数据文件、二进制扩展与 hook 提供的 hiddenimports 一并纳入。
# - asyncua 官方 hook 的分析图可能带上 tools→IPython→GUI 等可选链；本程序仅为无头 OPC UA 服务端，
#   通过 excludes 剔除这些包，显著减小体积且不影响服务端运行路径。
# - 龙蜥等若报 GLIBC 版本不符，需在「glibc 不高于目标机」的环境上构建（见 doc/user_manual.md）。

# -*- mode: python ; coding: utf-8 -*-

import sys

from PyInstaller.utils.hooks import collect_all

# 需要整包收集的第三方库（名称与 pip 包 import 名一致）
PACKAGES_TO_COLLECT_FULLY = (
    'asyncua',
    'cryptography',
)

# 与 onefile 分析相关的可调开关（避免魔法散落在 Analysis 参数里）
USE_UPX = False  # 企业 Linux 上 UPX 偶发与 .so 加载冲突，默认关闭更稳

# Linux onefile：引导程序需在某目录解压后再 dlopen libpython。若默认落在 /tmp 且该挂载为 noexec，
# 会出现 “Failed to load Python shared library”。此处把解压根目录写进引导程序（EXE 的 runtime_tmpdir），
# 一般使用 /var/tmp（多数发行版允许执行），且不再依赖运行前手工 export TMPDIR。
# 注意：POSIX 上该路径不支持 $HOME 等展开，须为绝对路径；若目标机策略禁止在此执行，请改成本单位允许的目录后重新打包。
# Windows 保持 None，沿用系统 Temp。
ONEFILE_RUNTIME_TMPDIR = "/var/tmp/ua_player_pyi" if sys.platform.startswith("linux") else None

# 无头服务端不需要的可选依赖（被 asyncua 等 hook 间接扫进分析图时剔除）
HEADLESS_BUILD_EXCLUDES = [
    'IPython',
    'matplotlib',
    'pytest',
    'black',
    'jedi',
    'parso',
    'PyQt6',
    'PySide6',
    'tkinter',
]

bundle_datas = []
bundle_binaries = []
bundle_hiddenimports = [
    'data_loader',
    'server_main',
    'session_monitor',
    'aiofiles',
    'sortedcontainers',
    'certifi',
]

for pkg in PACKAGES_TO_COLLECT_FULLY:
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    bundle_datas.extend(pkg_datas)
    bundle_binaries.extend(pkg_binaries)
    bundle_hiddenimports.extend(pkg_hidden)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=bundle_binaries,
    datas=bundle_datas,
    hiddenimports=bundle_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=HEADLESS_BUILD_EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ua_player_v7',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=USE_UPX,
    runtime_tmpdir=ONEFILE_RUNTIME_TMPDIR,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
