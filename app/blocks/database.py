"""Database Block - SQLite/PostgreSQL persistence"""
import logging
import os

from app.core.universal_base import UniversalBlock
from typing import Dict, Any, List, Optional
import json

logger = logging.getLogger(__name__)


def _default_sqlite_path() -> str:
    """Resolve the SQLite path: prefer DATA_DIR (the Render-mounted disk),
    fall back to ./data so local dev keeps working."""
    data_dir = os.getenv("DATA_DIR", "./data")
    return os.path.join(data_dir, "cerebrum.db")


class DatabaseBlock(UniversalBlock):
    """SQL Database - SQLite (local) or PostgreSQL (cloud)"""
    name = "database"
    version = "1.0.0"
    requires = ["config"]
    layer = 0  # Infrastructure layer
    tags = ["infrastructure", "database", "storage"]
    default_config = {
        "backend": "sqlite",
        "connection_string": None,  # resolved at init from DATA_DIR
    }

    ui_schema = {
        'input': {'type': 'json', 'accept': None, 'placeholder': 'JSON payload for the selected action', 'multiline': True},
        'output': {'type': 'json', 'fields': [{'name': 'rows', 'type': 'json', 'label': 'Rows'}]},
        'params': [{'name': 'action', 'type': 'select', 'label': 'Action', 'options': ['query', 'insert', 'update', 'delete', 'create_table', 'list_tables'], 'default': 'query'}],
        'quick_actions': [],
    }

    def __init__(self, hal_block=None, config: Optional[Dict[str, Any]] = None):
        """Both arguments optional, as UniversalBlock declares them.

        This block was the only one in the roster that narrowed its base
        class's signature to two REQUIRED arguments. Every sibling --
        storage, team, workflow, dashboard, capture -- takes
        ``(hal_block=None, config=None)``, and so does UniversalBlock itself,
        so every generic caller constructs blocks as ``block_cls()``.

        On ``database`` that raised, and the caller could only report the
        raw TypeError. From a booted generated platform, running a two-step
        pipeline whose first step writes a punch-list item:

            {"status": "partial", "results": [{"step_id": "step_0",
              "block": "database", "status": "failed",
              "error": "DatabaseBlock.__init__() missing 2 required
                        positional arguments: 'hal_block' and 'config'"}]}

        No workflow pipeline could ever include a database step. Nothing is
        invented here: the body already reads config with ``.get`` defaults
        and already falls back to ``_default_sqlite_path()``.
        """
        config = config or {}
        super().__init__(hal_block, config)
        self.backend = config.get("backend", "sqlite")
        configured = config.get("connection_string")
        if configured:
            self.connection_string = configured
        else:
            self.connection_string = f"sqlite:///{_default_sqlite_path()}"
        self._connection = None

    async def _legacy_initialize(self):
        """Initialize database connection"""
        logger.info("database: backend=%s connection=%s", self.backend, self.connection_string)

        if self.backend == "sqlite":
            import sqlite3
            db_path = self.connection_string.replace("sqlite:///", "")
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

            self._connection = sqlite3.connect(db_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._apply_sqlite_pragmas()

        elif self.backend == "postgresql":
            try:
                import psycopg2
                self._connection = psycopg2.connect(self.connection_string)
            except ImportError:
                logger.warning("database: psycopg2 not installed, using sqlite fallback")
                self.backend = "sqlite"
                import sqlite3
                fallback_path = _default_sqlite_path()
                fallback_dir = os.path.dirname(fallback_path)
                if fallback_dir:
                    os.makedirs(fallback_dir, exist_ok=True)
                self._connection = sqlite3.connect(fallback_path, check_same_thread=False)
                self._connection.row_factory = sqlite3.Row
                self._apply_sqlite_pragmas()

        return True

    def _apply_sqlite_pragmas(self) -> None:
        """WAL gives concurrent readers while a writer holds the lock — required
        once more than one request hits the DB at the same time. NORMAL sync
        with WAL is durable enough for our scale and ~5x faster than FULL."""
        try:
            cur = self._connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            self._connection.commit()
        except Exception:
            logger.exception("database: failed to apply SQLite pragmas")
    
    async def process(self, input_data: Dict, params: Dict = None) -> Dict:
        action = (params or {}).get("action") or (input_data.get("action") if isinstance(input_data, dict) else None)
        if action == "query":
            return await self._query(input_data)
        elif action == "insert":
            return await self._insert(input_data)
        elif action == "update":
            return await self._update(input_data)
        elif action == "delete":
            return await self._delete(input_data)
        elif action == "create_table":
            return await self._create_table(input_data)
        elif action == "list_tables":
            return await self._list_tables()
        return {"error": "Unknown action"}
    
    async def _query(self, data: Dict) -> Dict:
        """Execute SELECT query"""
        sql = data.get("sql")
        params = data.get("params", ())
        
        try:
            cursor = self._connection.cursor()
            cursor.execute(sql, params)
            
            rows = cursor.fetchall()
            columns = [description[0] for description in cursor.description] if cursor.description else []
            
            # Convert to dict
            results = []
            for row in rows:
                results.append(dict(zip(columns, row)))
            
            return {
                "rows": results,
                "count": len(results),
                "columns": columns
            }
            
        except Exception as e:
            return {"error": f"Query failed: {str(e)}", "sql": sql}
    
    async def _insert(self, data: Dict) -> Dict:
        """Insert data"""
        table = data.get("table")
        values = data.get("values", {})
        
        columns = ", ".join(values.keys())
        placeholders = ", ".join(["?" if self.backend == "sqlite" else "%s"] * len(values))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        
        try:
            cursor = self._connection.cursor()
            cursor.execute(sql, tuple(values.values()))
            self._connection.commit()
            
            # Get last insert id
            last_id = cursor.lastrowid if self.backend == "sqlite" else None
            
            return {
                "inserted": True,
                "id": last_id,
                "rows_affected": cursor.rowcount
            }
            
        except Exception as e:
            return {"error": f"Insert failed: {str(e)}"}
    
    async def _update(self, data: Dict) -> Dict:
        """Update data"""
        table = data.get("table")
        values = data.get("values", {})
        where = data.get("where", "")
        where_params = data.get("where_params", ())
        
        set_clause = ", ".join([f"{k} = ?" if self.backend == "sqlite" else f"{k} = %s" for k in values.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        
        try:
            cursor = self._connection.cursor()
            cursor.execute(sql, tuple(values.values()) + tuple(where_params))
            self._connection.commit()
            
            return {
                "updated": True,
                "rows_affected": cursor.rowcount
            }
            
        except Exception as e:
            return {"error": f"Update failed: {str(e)}"}
    
    async def _delete(self, data: Dict) -> Dict:
        """Delete data"""
        table = data.get("table")
        where = data.get("where", "")
        where_params = data.get("where_params", ())
        
        sql = f"DELETE FROM {table} WHERE {where}"
        
        try:
            cursor = self._connection.cursor()
            cursor.execute(sql, where_params)
            self._connection.commit()
            
            return {
                "deleted": True,
                "rows_affected": cursor.rowcount
            }
            
        except Exception as e:
            return {"error": f"Delete failed: {str(e)}"}
    
    async def _create_table(self, data: Dict) -> Dict:
        """Create table"""
        table = data.get("table")
        schema = data.get("schema", {})  # {column: type}
        
        columns_def = ", ".join([f"{col} {dtype}" for col, dtype in schema.items()])
        sql = f"CREATE TABLE IF NOT EXISTS {table} ({columns_def})"
        
        try:
            cursor = self._connection.cursor()
            cursor.execute(sql)
            self._connection.commit()
            
            return {"created": True, "table": table}
            
        except Exception as e:
            return {"error": f"Create table failed: {str(e)}"}
    
    async def _list_tables(self) -> Dict:
        """List all tables"""
        try:
            if self.backend == "sqlite":
                cursor = self._connection.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
            else:
                cursor = self._connection.cursor()
                cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
                tables = [row[0] for row in cursor.fetchall()]
            
            return {"tables": tables, "count": len(tables)}
            
        except Exception as e:
            return {"error": f"List tables failed: {str(e)}"}
    
    def health(self) -> Dict:
        h = {"name": self.name, "version": self.version}
        h["backend"] = self.backend
        h["connected"] = self._connection is not None
        return h
