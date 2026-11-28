import importlib.util
import json
import zipfile
from pathlib import Path


def test_extension_release_contains_runtime_only(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "package_extension", root / "scripts/package_extension.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "source"
    source.mkdir()
    for name in module.RUNTIME_FILES:
        content = (
            json.dumps({"version": "1.2.3", "manifest_version": 3})
            if name == "manifest.json"
            else "fictional runtime fixture"
        )
        (source / name).write_text(content, encoding="utf-8")
    (source / "profile.json").write_text('{"email":"private@example.com"}')
    (source / "connection.json").write_text('{"token":"private-token"}')
    (source / "fixtures").mkdir()
    (source / "fixtures/application.html").write_text("test-only permission fixture")
    (source.parent / "LICENSE").write_text("MIT License fixture", encoding="utf-8")

    archive = module.package(source, tmp_path / "release")
    assert archive.name == "JobPilot-Autofill-1.2.3.zip"
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {
            f"JobPilot-Autofill/{name}" for name in module.RUNTIME_FILES
        } | {"JobPilot-Autofill/LICENSE"}
        assert bundle.read("JobPilot-Autofill/LICENSE") == b"MIT License fixture"
        assert json.loads(bundle.read("JobPilot-Autofill/manifest.json"))["version"] == "1.2.3"
        assert b"private" not in b"".join(bundle.read(name) for name in bundle.namelist())
