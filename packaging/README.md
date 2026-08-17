# macOS app packaging

## py2app menu-bar bundle

Build a double-clickable, ad-hoc signed `anon-proxy.app` from the
`anon-proxy-menubar` entry point:

```bash
uv sync --extra package --extra menubar
ANON_PROXY_CODESIGN_IDENTITY=- uv run python packaging/setup_app.py py2app
```

The signing identity defaults to ad-hoc (`-`). The build script signs the
bundle after py2app creates it. A Developer ID build can use the same script by
setting the identity:

```bash
ANON_PROXY_CODESIGN_IDENTITY="Developer ID Application: Your Name" \
  uv run python packaging/setup_app.py py2app
xcrun notarytool submit dist/anon-proxy.app
xcrun stapler staple dist/anon-proxy.app
```

## PyInstaller bundle

This builds an unsigned, local-use macOS menu-bar app. It intentionally uses the
torch-free runtime: install `onnx`, `menubar`, and `bundle`, but not `torch`.

```bash
uv sync --extra onnx --extra menubar --extra bundle
PYINSTALLER_CONFIG_DIR=/tmp/anon-proxy-pyinstaller \
  uv run --extra onnx --extra menubar --extra bundle \
  pyinstaller packaging/anon-proxy.spec --noconfirm
```

The output is `dist/anon-proxy.app`.

Model weights are not bundled. On first proxy start, the app downloads the
`openai/privacy-filter` ONNX q4f16 graph and sidecar into the Hugging Face cache.
That keeps the app bundle smaller and lets the normal cache handle updates.

Developer ID signing, notarization, and DMG packaging require a user-provisioned
Apple Developer ID certificate and notarytool profile.
