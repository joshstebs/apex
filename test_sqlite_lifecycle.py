"""SQLite transactions commit/rollback and close deterministically, without GC."""
import sqlite3
import tempfile
import os
from database import Database

with tempfile.TemporaryDirectory() as directory:
    database = Database(os.path.join(directory, "lifecycle.db"))
    with database.get_connection() as connection:
        connection.execute("CREATE TABLE lifecycle_test (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO lifecycle_test VALUES (1)")
    try:
        connection.execute("SELECT 1")
        raise AssertionError("The connection must close at context exit")
    except sqlite3.ProgrammingError:
        pass
    try:
        with database.get_connection() as failed:
            failed.execute("INSERT INTO lifecycle_test VALUES (2)")
            raise ValueError("Synthetic transaction failure")
    except ValueError:
        pass
    try:
        failed.execute("SELECT 1")
        raise AssertionError("Failed transactions must also close")
    except sqlite3.ProgrammingError:
        pass
    with database.get_connection() as connection:
        assert [row[0] for row in connection.execute("SELECT id FROM lifecycle_test")] == [1]
print("PASS: SQLite commit, rollback, close and immediate temporary-directory cleanup")
