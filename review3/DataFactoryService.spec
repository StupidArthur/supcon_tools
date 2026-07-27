# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for DataFactory 常驻服务（todo.md §8.1）。
#
# 输出：DataFactoryService.exe
#   - 内置 Python 解释器（PyInstaller bootloader）
#   - 内置依赖：asyncua / PyYAML / numpy / python-dateutil / fastapi / uvicorn / pydantic
#   - 内置运行模块：controller / components / datacenter
#   - 无控制台窗口（console=False → noconsole，TODO.md §8.1 明确要求）
#   - 不依赖系统 Python
#   - 不依赖当前工作目录（通过 sys._MEIPASS 访问 data）
#   - 可通过 --service 独立启动
#
# 构建示例：
#   cd review3
#   pyinstaller DataFactoryService.spec
#
# 产物：review3/dist/DataFactoryService.exe
# 发布前将其复制到 config-tool.exe 同级目录。

block_cipher = None

a = Analysis(
    ['standalone_main.py'],
    pathex=[''],
    binaries=[],
    datas=[
        ('config', 'config'),
        ('components/export_templates/templates', 'components/export_templates/templates'),
    ],
    hiddenimports=[
        # 第三方依赖
        'asyncua',
        'asyncua.client',
        'asyncua.server',
        'asyncua.ua',
        'PyYAML',
        'dateutil',
        'dateutil.parser',
        'dateutil.tz',
        'numpy',
        'numpy.core',
        # 服务相关（todo.md §4 / §5）
        'fastapi',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'uvicorn',
        'uvicorn.config',
        'uvicorn.server',
        'uvicorn.logging',
        'logging.config',
        'logging.handlers',
        'pydantic',
        'pydantic.fields',
        # 项目内部模块（确保它们被打进 exe）
        'components',
        'components.programs',
        'components.functions',
        'components.export_templates',
        'components.export_templates.csv_exporter',
        'components.export_templates.excel_exporter',
        'components.export_templates.template_manager',
        'components.export_templates.synthetic_export_file_generator',
        'controller',
        'controller.parser',
        'controller.engine',
        'controller.clock',
        'controller.variable',
        'controller.expression',
        'controller.factory',
        'controller.instance',
        'controller.realtime_config_compiler',
        'datacenter',
        'datacenter.opcua_server',
        'datacenter.engine_api',
        'datacenter.batch_store',
        'datacenter.batch_manager',
        'datacenter.force_manager',
        'datacenter.quality_manager',
        # SQLite（batch_store 依赖）
        'sqlite3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不需要 GUI / 异步 web 客户端 / 浏览器集成
        'tkinter',
        'PyQt5',
        'PyQt6',
        'wx',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DataFactoryService',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                  # noconsole：无控制台窗口（todo.md §8.1）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)