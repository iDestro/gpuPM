from pathlib import Path
import sqlite3
import subprocess
import sys


def test_backup_includes_committed_wal_and_refuses_overwrite(tmp_path):
    source = tmp_path / "app.sqlite"
    destination = tmp_path / "backup.sqlite"
    script = Path(__file__).resolve().parents[3] / "scripts/backup.py"
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE records(value TEXT)")
        db.execute("INSERT INTO records VALUES('committed')")
        db.commit()
        db.execute("INSERT INTO records VALUES('not committed')")
        subprocess.run(
            [sys.executable, str(script), str(source), str(destination)], check=True, capture_output=True
        )
        with sqlite3.connect(destination) as backup:
            assert backup.execute("SELECT value FROM records").fetchall() == [("committed",)]
            assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert destination.stat().st_mode & 0o777 == 0o600
        before = destination.read_bytes()
        refused = subprocess.run(
            [sys.executable, str(script), str(source), str(destination)], capture_output=True
        )
        assert refused.returncode != 0 and destination.read_bytes() == before
