"""Package metadata, console-script contract, and torch-free bundle layout."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
PYINSTALLER_SPEC = Path(__file__).resolve().parent.parent / "packaging/anon-proxy.spec"


def _pyproject() -> dict:
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)


def test_repo_urls_point_at_byliu_labs():
    urls = _pyproject()["project"]["urls"]
    for key in ("Homepage", "Repository", "Issues"):
        assert "byliu-labs" in urls[key], f"{key} still points at {urls[key]}"


def test_console_scripts_present():
    scripts = _pyproject()["project"]["scripts"]
    assert set(scripts) == {
        "anon-proxy",
        "anon-proxy-bench",
        "anon-proxy-build-app",
        "anon-proxy-capture-report",
        "anon-proxy-eval",
        "anon-proxy-menubar",
        "anon-proxy-store",
    }
    assert scripts["anon-proxy"] == "anon_proxy.cli:main"
    assert scripts["anon-proxy-bench"] == "anon_proxy.bench:main"
    assert scripts["anon-proxy-build-app"] == "anon_proxy.app_bundle:main"
    assert scripts["anon-proxy-eval"] == "anon_proxy.eval:main"


def test_torch_is_not_a_base_dependency():
    deps = _pyproject()["project"]["dependencies"]
    assert not any(d.split(">")[0].split("=")[0].strip() == "torch" for d in deps), (
        "torch must be optional so the base install stays torch-free; found it in "
        "[project.dependencies]"
    )


def test_torch_extra_exists_with_version_floor():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert "torch" in extras, "expected a 'torch' optional-dependencies extra"
    assert any("torch>=2.11.0" in d for d in extras["torch"]), (
        "torch extra must pin the >=2.11.0 floor"
    )


def test_transformers_stays_a_base_dependency():
    deps = _pyproject()["project"]["dependencies"]
    assert any(d.startswith("transformers") for d in deps)


def test_onnx_extra_still_present():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert "onnx" in extras and any("onnxruntime" in d for d in extras["onnx"])


def test_bundle_extra_installs_pyinstaller():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert "bundle" in extras, "expected a 'bundle' extra for app packaging"
    assert any(d.startswith("pyinstaller") for d in extras["bundle"])


def test_package_extra_installs_py2app_on_macos():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert "package" in extras, "expected a 'package' extra for py2app packaging"
    assert any(d.startswith("py2app") for d in extras["package"])


def test_pyinstaller_spec_excludes_torch():
    spec = PYINSTALLER_SPEC.read_text()
    assert "excludes=" in spec
    assert '"torch"' in spec
