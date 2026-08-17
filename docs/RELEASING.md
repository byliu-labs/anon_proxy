# Releasing

Releases are built from git tags in the canonical fork:
`byliu-labs/anon_proxy`.

## Version Bump

1. Choose the next semantic version, for example `0.1.1`.
2. Update `version` in `pyproject.toml`.
3. Move the relevant `CHANGELOG.md` entries from `Unreleased` to the new
   version section.
4. Run the local gate:

   ```bash
   ./presubmit.sh
   uv build
   ```

5. Commit the version and changelog update.
6. Create and push a tag:

   ```bash
   git tag v0.1.1
   git push origin v0.1.1
   ```

The release workflow drafts a GitHub Release and attaches the wheel, sdist, and
macOS DMG when the macOS packaging job succeeds.

## PyPI

PyPI publishing is deliberately disabled. Before enabling it, decide the project
name, create the PyPI project, and configure Trusted Publisher or a repository
secret. Do not add a plaintext token to the repo.

## macOS App

The tag workflow builds an unsigned macOS launcher app, packages it into a DMG,
and attaches that DMG to the draft release. The app launches
`anon-proxy-menubar` from the user's environment; the heavier self-contained
PyInstaller packaging path remains documented in `packaging/README.md`.

Unsigned builds trigger Gatekeeper warnings. The release smoke check is:

1. Download the DMG from the draft release.
2. Mount it on macOS.
3. Make sure `anon-proxy-menubar` is installed on `PATH`.
4. Drag `anon-proxy.app` to Applications or run it from the mounted volume.
5. Confirm the menu-bar indicator opens and can start the local proxy.

Signing and notarization require an Apple Developer ID certificate and
notarization credentials stored as GitHub secrets. Add that only after the
certificate decision is made.
