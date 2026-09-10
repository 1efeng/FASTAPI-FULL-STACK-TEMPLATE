from pathlib import Path


def test_backend_architecture_paths() -> None:
    app_root = Path("app")

    required_paths = (
        app_root / "core",
        app_root / "db" / "base.py",
        app_root / "db" / "session.py",
        app_root / "db" / "models.py",
        app_root / "db" / "repository.py",
        app_root / "integrations" / "email.py",
        app_root / "system" / "api.py",
        app_root / "auth",
        app_root / "user",
        app_root / "demo",
        app_root / "agent" / "agent.py",
        app_root / "agent" / "middleware.py",
        app_root / "agent" / "skills",
        app_root / "chat" / "protocol" / "schema.py",
        app_root / "chat" / "protocol" / "run_registry.py",
        app_root / "chat" / "protocol" / "session.py",
        app_root / "chat" / "protocol" / "adapter.py",
        Path("alembic"),
        Path("scripts/prestart.py"),
        Path("scripts/init_data.py"),
    )
    assert all(path.exists() for path in required_paths)

    removed_paths = (
        app_root / "modules",
        app_root / "infra",
        app_root / "utils",
        app_root / "common",
        app_root / "alembic",
        app_root / "core" / "base_model.py",
        app_root / "core" / "base_repository.py",
        app_root / "core" / "base_schema.py",
        app_root / "backend_pre_start.py",
        app_root / "tests_pre_start.py",
        app_root / "initial_data.py",
        app_root / "chat" / "runtime",
        app_root / "chat" / "engine",
        app_root / "chat" / "scheduler",
        app_root / "chat" / "durable",
    )
    assert all(not path.exists() for path in removed_paths)

    forbidden_imports = (
        "app." + "modules",
        "app." + "infra",
        "app." + "utils",
        "app." + "common",
        "app." + "item",
        "app.core." + "base_model",
        "app.core." + "base_repository",
        "app.core." + "base_schema",
    )
    offenders: list[str] = []
    for root in (Path("app"), Path("tests"), Path("scripts")):
        for path in root.rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            if any(value in content for value in forbidden_imports):
                offenders.append(str(path))
    assert not offenders, f"Legacy architecture paths remain in: {offenders}"
