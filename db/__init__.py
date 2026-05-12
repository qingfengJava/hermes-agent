"""
数据库抽象层。

支持 PostgreSQL、MySQL 和 SQLite（向后兼容）三种后端。
通过环境变量 HERMES_DB_TYPE 和 HERMES_DB_URL 控制切换。

未配置共享数据库时自动降级为本地 SQLite，确保零影响。
"""

from db.connection import DatabaseManager, get_db_manager, init_database
from db.dialect import DialectHelper, get_dialect, DbType
from db.id_generator import IdGenerator, get_id_generator
from db.adapter import ConnectionAdapter, CursorAdapter, RowAdapter
from db.schema import init_schema

__all__ = [
    "DatabaseManager",
    "get_db_manager",
    "init_database",
    "DialectHelper",
    "get_dialect",
    "DbType",
    "IdGenerator",
    "get_id_generator",
    "ConnectionAdapter",
    "CursorAdapter",
    "RowAdapter",
    "init_schema",
]
