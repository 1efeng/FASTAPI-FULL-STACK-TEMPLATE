from pathlib import Path


def test_legacy_import_paths_are_gone() -> None:
    assert not Path("app/modules").exists()
    assert not Path("app/utils/email.py").exists()

    forbidden_imports = (
        "app." + "modules",
        "app.utils." + "email",
    )
    offenders: list[str] = []

    for root in (Path("app"), Path("tests")):
        for path in root.rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            if any(legacy_import in content for legacy_import in forbidden_imports):
                offenders.append(str(path))

    assert not offenders, f"Legacy import paths remain in: {offenders}"
