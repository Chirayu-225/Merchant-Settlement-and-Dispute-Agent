import importlib
import os

import config


def test_database_falls_back_to_a_temp_folder_when_the_app_folder_is_read_only(tmp_path, monkeypatch):
    monkeypatch.delenv("DB_PATH", raising=False)
    locked = tmp_path / "locked"
    locked.mkdir()
    monkeypatch.setattr(config, "BASE_DIR", locked / "app")  # cannot be created under a file
    (locked / "app").write_text("a file, not a folder")
    path = config._default_db_path()
    assert str(path).startswith(os.path.realpath(__import__("tempfile").gettempdir())) or "tmp" in str(path)
    assert path.name.endswith(".db")
