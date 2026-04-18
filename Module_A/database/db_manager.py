import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from Module_A.database.table import Table


class DatabaseManager:
    def __init__(self):
        self._dbs = {}   # { db_name: { table_name: Table } }

    # Database-level operations
    def create_database(self, db_name):
        if db_name in self._dbs:
            raise ValueError(f"Database '{db_name}' already exists")
        self._dbs[db_name] = {}

    def drop_database(self, db_name):
        self._dbs.pop(db_name, None)

    def list_databases(self):
        return list(self._dbs.keys())

    # Table-level operations
    def create_table(self, db_name, table_name, schema, order=8, search_key=None):
        if db_name not in self._dbs:
            raise ValueError(f"Database '{db_name}' does not exist")
        if table_name in self._dbs[db_name]:
            # Idempotent: silently skip if table already exists.
            # Mirrors IF NOT EXISTS behaviour used in create_schema().
            return
        self._dbs[db_name][table_name] = Table(
            table_name, schema, order, search_key
        )

    def drop_table(self, db_name, table_name):
        self._dbs.get(db_name, {}).pop(table_name, None)

    def list_tables(self, db_name):
        return list(self._dbs.get(db_name, {}).keys())

    def get_table(self, db_name, table_name):
        try:
            return self._dbs[db_name][table_name]
        except KeyError:
            raise ValueError(
                f"Table '{db_name}.{table_name}' does not exist"
            )