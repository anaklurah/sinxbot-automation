import os

if os.path.exists('dist/sinx-automation.exe'):
    exe_source = 'dist/sinx-automation.exe'
elif os.path.exists('../downloads/sinx-automation.exe'):
    exe_source = '../downloads/sinx-automation.exe'
else:
    exe_source = 'sinx-automation.exe'

a = Analysis(
    ['installer.py'],
    pathex=[],
    binaries=[],
    datas=[
        (exe_source, '.'),
        ('icon.ico', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL'],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='install',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
