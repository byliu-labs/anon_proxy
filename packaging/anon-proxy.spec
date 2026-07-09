# Build from the repository root:
#   uv run --extra onnx --extra menubar --extra bundle pyinstaller packaging/anon-proxy.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

project_root = Path(SPECPATH).parent

datas, binaries, hiddenimports = [], [], []
for pkg in ("transformers", "tokenizers", "huggingface_hub", "onnxruntime", "numpy"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

datas += collect_data_files("anon_proxy", includes=["assets/dino/**/*.png"])

a = Analysis(
    [str(project_root / "anon_proxy/menubar/__main__.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["anon_proxy.server", "rumps"],
    excludes=["torch", "tensorflow", "jax"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="anon-proxy",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="anon-proxy")
app = BUNDLE(
    coll,
    name="anon-proxy.app",
    icon=None,
    bundle_identifier="com.anon-proxy.menubar",
    info_plist={
        "LSUIElement": True,
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
    },
)
