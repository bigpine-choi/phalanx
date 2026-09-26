"""OS independent fixtures generated once by production history/features/selection.

No Linux repository import. Raw serialized models and selection preserve source
hashes; database creation below is test-only. Production desktop never creates DBs.
"""

import gzip
import json
import os
import sqlite3
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "desktop"


def desktop_inputs(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    database = directory / "합성 history.sqlite3"
    selection = directory / "선정 selection.json"
    selection.write_bytes((FIXTURES / "selection.json").read_bytes())
    view = json.loads(gzip.decompress((FIXTURES / "history-view.json.gz").read_bytes()))
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE jobs (job_id TEXT PRIMARY KEY, job_json TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE symbols (job_id TEXT NOT NULL REFERENCES jobs(job_id), "
            "ordinal INTEGER NOT NULL, state_json TEXT NOT NULL, PRIMARY KEY(job_id, ordinal))"
        )
        connection.execute("PRAGMA user_version=1")
        connection.execute("PRAGMA application_id=1346914353")
        connection.execute(
            "INSERT INTO jobs VALUES (?,?)", (view["job"]["job_id"], json.dumps(view["job"]))
        )
        for index, symbol in enumerate(view["symbols"]):
            connection.execute(
                "INSERT INTO symbols VALUES (?,?,?)",
                (view["job"]["job_id"], index, json.dumps(symbol)),
            )
        connection.commit()
    finally:
        connection.close()
    if os.name != "nt":
        database.chmod(0o600)
    return database, selection
