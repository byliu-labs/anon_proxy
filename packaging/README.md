# macOS app packaging

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

Signing, notarization, and DMG packaging are intentionally not included here.
They require a user-provisioned Apple Developer ID certificate and notarytool
profile.
