"""Database connection and initialization."""

import os
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from src.util.logging import get_logger

logger = get_logger("storage.db")


class Database:
    """Database connection manager."""

    def __init__(self, dsn: str):
        """
        Initialize database connection.

        Args:
            dsn: PostgreSQL connection string
        """
        self.dsn = dsn
        self._conn = None

    def connect(self):
        """Establish database connection."""
        if self._conn is None or self._conn.closed:
            try:
                self._conn = psycopg2.connect(self.dsn)
                self._conn.autocommit = False
                logger.info("Database connection established")
            except psycopg2.Error as e:
                logger.error(f"Database connection failed: {e}")
                raise

    def close(self):
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            logger.info("Database connection closed")

    @property
    def conn(self):
        """Get database connection, connecting if needed."""
        if self._conn is None or self._conn.closed:
            self.connect()
        return self._conn

    def cursor(self, cursor_factory=RealDictCursor):
        """
        Get a database cursor.

        Args:
            cursor_factory: Cursor factory class

        Returns:
            Database cursor
        """
        return self.conn.cursor(cursor_factory=cursor_factory)

    def commit(self):
        """Commit current transaction."""
        if self._conn:
            self._conn.commit()

    def rollback(self):
        """Rollback current transaction."""
        if self._conn:
            self._conn.rollback()

    def execute(self, query: str, params: tuple = None):
        """
        Execute a query.

        Args:
            query: SQL query
            params: Query parameters

        Returns:
            Cursor with results
        """
        cur = self.cursor()
        cur.execute(query, params)
        return cur

    def execute_script(self, script: str):
        """
        Execute a SQL script.

        Args:
            script: SQL script content
        """
        cur = self.cursor()
        cur.execute(script)
        self.commit()

    def init_schema(self, ddl_path: Optional[str] = None):
        """
        Initialize database schema from DDL file.

        Args:
            ddl_path: Path to DDL SQL file
        """
        if ddl_path is None:
            # Find DDL relative to this file
            ddl_path = Path(__file__).parent / "ddl.sql"

        if not Path(ddl_path).exists():
            raise FileNotFoundError(f"DDL file not found: {ddl_path}")

        logger.info(f"Initializing schema from {ddl_path}")

        with open(ddl_path, "r", encoding="utf-8") as f:
            ddl = f.read()

        self.execute_script(ddl)
        logger.info("Schema initialized successfully")

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


def get_database(dsn: str) -> Database:
    """
    Factory function to get database instance.

    Args:
        dsn: PostgreSQL connection string

    Returns:
        Database instance
    """
    return Database(dsn)
