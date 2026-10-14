"""Consistent SQLite backup, including committed WAL records. No file deletion."""

import argparse
import os
import sqlite3
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
if not args.source.is_file() or args.destination.exists():
    parser.error("source must exist; destination must be new")
args.destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
fd = os.open(
    args.destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
)
os.close(fd)
with sqlite3.connect(f"file:{args.source.resolve()}?mode=ro", uri=True) as source:
    with sqlite3.connect(args.destination) as destination:
        source.backup(destination)
print("Consistent database backup created.")
