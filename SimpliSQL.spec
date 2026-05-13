# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['Simplisql.py'],
    pathex=['.'],
    binaries=[
        # llama_cpp native DLLs – must land in llama_cpp/lib/ inside the bundle
        ('.venv/Lib/site-packages/llama_cpp/lib/ggml-base.dll', 'llama_cpp/lib'),
        ('.venv/Lib/site-packages/llama_cpp/lib/ggml-cpu.dll',  'llama_cpp/lib'),
        ('.venv/Lib/site-packages/llama_cpp/lib/ggml.dll',      'llama_cpp/lib'),
        ('.venv/Lib/site-packages/llama_cpp/lib/llama.dll',     'llama_cpp/lib'),
        ('.venv/Lib/site-packages/llama_cpp/lib/mtmd.dll',      'llama_cpp/lib'),
    ],
    datas=[
        ('sql.ico', '.'),
        ('sql.png', '.'),
        ('Auto_Workflow', 'Auto_Workflow'),
        ('utils', 'utils'),
        ('core', 'core'),
        ('ai', 'ai'),
        ('ui', 'ui'),
        ('docs', 'docs'),
        ('models', 'models'),
    ],
    hiddenimports=[
        # Qt
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtPrintSupport',
        # Database
        'duckdb',
        # Data handling
        'pandas',
        'pandas.core',
        'pyarrow',
        'pyarrow.parquet',
        'pyarrow.lib',
        # Charting
        'plotly',
        'plotly.graph_objects',
        'plotly.subplots',
        'matplotlib',
        'matplotlib.pyplot',
        'matplotlib.backends.backend_qt5agg',
        # PDF export
        'reportlab',
        'reportlab.lib',
        'reportlab.lib.pagesizes',
        'reportlab.lib.styles',
        'reportlab.lib.units',
        'reportlab.lib.colors',
        'reportlab.platypus',
        # Utilities
        'pyperclip',
        'requests',
        'logging.handlers',
        # AI (local model)
        'llama_cpp',
        'huggingface_hub',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5',
        'openai',
        'anthropic',
        'google',
        'google.generativeai',
        'torch',
        'tensorflow',
        'sklearn',
        'scipy',
        'jupyter',
        'IPython',
        'pytest',
        'sphinx',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SimpliSQL',
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
    icon=['sql.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SimpliSQL',
)
