import pytest

from gpupm.cli import main
from gpupm.api.auth import Auth
from gpupm.db.session import database


def test_admin_cli_prompts_without_password_argument(tmp_path, monkeypatch):
    monkeypatch.setattr("gpupm.cli.getpass.getpass", lambda prompt: "Strong-demo-secret-42")
    path = tmp_path / "app.db"
    main(["admin-add", "--username", "admin", "--database", str(path)])
    _, sessions = database(path)
    _, identity = Auth(sessions).login("admin", "Strong-demo-secret-42", "cli-test")
    assert identity["username"] == "admin"


def test_cli_rejects_plaintext_password_argument():
    with pytest.raises(SystemExit):
        main(["admin-add", "--username", "admin", "--password", "secret"])


def test_init_records_device_ids_without_mutating_accounts(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr("gpupm.cli.os.geteuid", lambda: 0)
    home = tmp_path / "home"
    data = tmp_path / "data"
    home.mkdir()
    data.mkdir()
    config = tmp_path / "agent.json"
    main(
        [
            "init-config",
            "--path",
            str(config),
            "--api-uid",
            "1000",
            "--home-base",
            str(home),
            "--data-base",
            str(data),
            "--maintenance-user",
            "operator",
        ]
    )
    values = json.loads(config.read_text())
    assert values["home_dev_id"] == home.stat().st_dev
    assert values["data_dev_id"] == data.stat().st_dev
    assert values["allow_mutations"] is False
    assert not list(home.iterdir()) and not list(data.iterdir())
    assert config.stat().st_mode & 0o777 == 0o600
