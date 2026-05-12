"""
数据库连接管理器。

支持三种后端：
- PostgreSQL：通过 psycopg2（ThreadedConnectionPool）
- MySQL：通过 mysql-connector-python（MySQLConnectionPool）
- SQLite：通过 sqlite3（向后兼容，默认）

通过环境变量控制：
- HERMES_DB_TYPE: postgresql | mysql | sqlite（默认 sqlite）
- HERMES_DB_URL:  完整的 JDBC 风格连接字符串

    PostgreSQL: postgresql://user:pass@localhost:5432/hermes
    MySQL:      mysql://user:pass@localhost:3306/hermes

未配置 HERMES_DB_URL 时自动降级为本地 SQLite，零影响。

所有接口均为同步方法，与现有 Agent 代码完全兼容。
"""

import logging
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from db.dialect import DbType, DialectHelper
from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_PATH = get_hermes_home() / "state.db"

# 连接池大小
POOL_MIN_SIZE = int(os.getenv("HERMES_DB_POOL_MIN", "2"))
POOL_MAX_SIZE = int(os.getenv("HERMES_DB_POOL_MAX", "20"))


class DatabaseManager:
    """
    数据库连接管理器（同步接口）。

    线程安全。内部根据数据库类型使用不同的连接池策略：
    - PostgreSQL: psycopg2.pool.ThreadedConnectionPool
    - MySQL:      mysql.connector.pooling.MySQLConnectionPool
    - SQLite:     sqlite3 + threading.Lock（兼容模式）

    用法:
        mgr = DatabaseManager()
        mgr.initialize()
        row = mgr.fetchone("SELECT * FROM sessions WHERE id = ?", session_id)
        mgr.close()
    """

    def __init__(self, db_type: DbType = None, db_url: str = None):
        """
        参数:
            db_type: 数据库类型，None 时从 HERMES_DB_TYPE 检测
            db_url:  连接字符串，None 时从 HERMES_DB_URL 检测
        """
        self.db_type = db_type or self._detect_db_type()
        self.db_url = db_url or self._detect_db_url()
        self.dialect = DialectHelper(self.db_type)
        self._pool = None
        self._initialized = False
        self._lock = threading.Lock()
        # SQLite 模式下每个线程独立连接
        self._sqlite_connections: Dict[int, Any] = {}
        self._thread_local = threading.local()

    # ── 自动检测 ──────────────────────────────────────────────

    @staticmethod
    def _detect_db_type() -> DbType:
        """
        从环境变量检测数据库类型。

        - 未设置 → SQLite（向后兼容）
        - mysql → MySQL（生产环境推荐）
        - postgresql/postgres/pg → PostgreSQL
        """
        db_type_str = os.getenv("HERMES_DB_TYPE", "sqlite").lower()
        if db_type_str == "mysql":
            return DbType.MYSQL
        elif db_type_str in ("postgresql", "postgres", "pg"):
            return DbType.POSTGRESQL
        else:
            return DbType.SQLITE

    def _detect_db_url(self) -> Optional[str]:
        """
        从环境变量或默认值检测数据库连接 URL。

        MySQL 默认：mysql://root:root@127.0.0.1:3306/hermes
        PostgreSQL 默认：postgresql://root:root@127.0.0.1:5432/hermes
        SQLite 默认：~/.hermes/state.db
        """
        url = os.getenv("HERMES_DB_URL")
        if url:
            return url
        if self.db_type == DbType.MYSQL:
            return "mysql://root:root@127.0.0.1:3306/hermes"
        elif self.db_type == DbType.POSTGRESQL:
            return "postgresql://root:root@127.0.0.1:5432/hermes"
        else:
            return str(DEFAULT_SQLITE_PATH)

    # ── 生命周期 ──────────────────────────────────────────────

    def initialize(self) -> None:
        """初始化连接池。幂等，多次调用安全。"""
        with self._lock:
            if self._initialized:
                return
            if self.db_type == DbType.SQLITE:
                self._init_sqlite()
            elif self.db_type == DbType.POSTGRESQL:
                self._init_postgresql()
            elif self.db_type == DbType.MYSQL:
                self._init_mysql()
            else:
                raise ValueError(f"不支持的数据库类型: {self.db_type}")
            self._initialized = True
            logger.info("数据库连接已初始化: type=%s url=%s", self.db_type.value,
                        self._mask_url())

    def _mask_url(self) -> str:
        """脱敏后的连接 URL（隐藏密码）"""
        if not self.db_url or self.db_type == DbType.SQLITE:
            return self.db_url or ""
        try:
            p = urlparse(self.db_url)
            if p.password:
                return p._replace(netloc=f"{p.username}:***@{p.hostname}:{p.port}").geturl()
        except Exception:
            pass
        return self.db_url

    def close(self) -> None:
        """关闭所有连接"""
        with self._lock:
            if not self._initialized:
                return
            if self.db_type == DbType.SQLITE:
                for conn in self._sqlite_connections.values():
                    try:
                        conn.close()
                    except Exception:
                        pass
                self._sqlite_connections.clear()
            elif self.db_type == DbType.POSTGRESQL:
                if self._pool:
                    self._pool.closeall()
            elif self.db_type == DbType.MYSQL:
                # MySQLConnectionPool 没有 closeall，需要逐个关闭
                pass
            self._initialized = False
            logger.info("数据库连接已关闭")

    # ── SQLite 初始化 ─────────────────────────────────────────

    def _init_sqlite(self) -> None:
        """SQLite 模式：不做任何初始化，连接按线程懒创建"""
        db_path = self.db_url or str(DEFAULT_SQLITE_PATH)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_sqlite_conn(self):
        """获取当前线程的 SQLite 连接（线程隔离）"""
        conn = getattr(self._thread_local, "conn", None)
        if conn is None:
            import sqlite3
            db_path = self.db_url or str(DEFAULT_SQLITE_PATH)
            conn = sqlite3.connect(
                db_path,
                check_same_thread=True,
                timeout=1.0,
                isolation_level=None,
            )
            conn.row_factory = sqlite3.Row
            # WAL 模式
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA foreign_keys=ON")
            self._thread_local.conn = conn
        return conn

    # ── PostgreSQL 初始化 ─────────────────────────────────────

    def _init_postgresql(self) -> None:
        """初始化 PostgreSQL 线程安全连接池"""
        import psycopg2
        from psycopg2 import pool as pg_pool

        parsed = urlparse(self.db_url)
        dsn_parts = {
            "host": parsed.hostname or "127.0.0.1",
            "port": parsed.port or 5432,
            "dbname": (parsed.path or "/hermes").lstrip("/"),
            "user": parsed.username or "hermes",
            "password": parsed.password or "",
        }
        dsn = " ".join(f"{k}={v}" for k, v in dsn_parts.items() if v is not None)

        try:
            self._pool = pg_pool.ThreadedConnectionPool(
                minconn=POOL_MIN_SIZE,
                maxconn=POOL_MAX_SIZE,
                dsn=dsn,
            )
        except ImportError:
            raise ImportError(
                "使用 PostgreSQL 需要安装 psycopg2-binary: "
                "pip install psycopg2-binary"
            )

    # ── MySQL 初始化 ──────────────────────────────────────────

    def _init_mysql(self) -> None:
        """初始化 MySQL 连接池"""
        try:
            from mysql.connector.pooling import MySQLConnectionPool
        except ImportError:
            raise ImportError(
                "使用 MySQL 需要安装 mysql-connector-python: "
                "pip install mysql-connector-python"
            )

        parsed = urlparse(self.db_url)
        self._pool = MySQLConnectionPool(
            pool_name="hermes_pool",
            pool_size=POOL_MAX_SIZE,
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 3306,
            user=parsed.username or "root",
            password=parsed.password or "",
            database=(parsed.path or "/hermes").lstrip("/"),
            autocommit=True,
        )

    # ── 连接获取/释放 ──────────────────────────────────────────

    @contextmanager
    def _connection(self):
        """上下文管理器：获取和释放数据库连接"""
        conn = self._acquire()
        try:
            # MySQL connector 使用 cursor，其他使用连接本身
            if self.db_type == DbType.MYSQL:
                cursor = conn.cursor(dictionary=True)
                try:
                    yield cursor
                finally:
                    cursor.close()
            else:
                yield conn
        finally:
            self._release(conn)

    def _acquire(self):
        """获取连接"""
        if self.db_type == DbType.SQLITE:
            return self._get_sqlite_conn()
        elif self.db_type == DbType.POSTGRESQL:
            return self._pool.getconn()
        elif self.db_type == DbType.MYSQL:
            return self._pool.get_connection()

    def _release(self, conn) -> None:
        """释放连接"""
        if self.db_type == DbType.POSTGRESQL:
            self._pool.putconn(conn)
        elif self.db_type == DbType.MYSQL:
            if hasattr(conn, "close"):
                conn.close()
        # SQLite 不释放（线程级别复用）

    # ── 统一查询接口 ──────────────────────────────────────────

    def execute(self, sql: str, *params) -> int:
        """
        执行写操作（INSERT/UPDATE/DELETE），返回影响行数。

        用法:
            rowcount = mgr.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                new_title, session_id
            )
        """
        if self._needs_placeholder_conversion(self.db_type):
            sql = self._adapt_sql(sql, self.db_type)

        with self._connection() as conn:
            if self.db_type == DbType.POSTGRESQL:
                cursor = conn.cursor()
                cursor.execute(sql, params or ())
                rowcount = cursor.rowcount
                cursor.close()
                conn.commit()
                return rowcount
            elif self.db_type == DbType.MYSQL:
                conn.execute(sql, params or ())
                return conn.rowcount
            else:
                # SQLite
                conn.execute(sql, params or ())
                return conn.total_changes

    def fetchone(self, sql: str, *params) -> Optional[Dict[str, Any]]:
        """
        执行查询，返回单行字典，无结果返回 None。

        用法:
            session = mgr.fetchone("SELECT * FROM sessions WHERE id = ?", sid)
        """
        if self._needs_placeholder_conversion(self.db_type):
            sql = self._adapt_sql(sql, self.db_type)

        with self._connection() as conn:
            if self.db_type == DbType.POSTGRESQL:
                cursor = conn.cursor()
                cursor.execute(sql, params or ())
                row = cursor.fetchone()
                cursor.close()
                if row:
                    desc = [d[0] for d in cursor.description]
                    return dict(zip(desc, row))
                return None
            elif self.db_type == DbType.MYSQL:
                conn.execute(sql, params or ())
                return conn.fetchone()
            else:
                # SQLite
                cursor = conn.execute(sql, params or ())
                row = cursor.fetchone()
                return dict(row) if row else None

    def fetchall(self, sql: str, *params) -> List[Dict[str, Any]]:
        """
        执行查询，返回多行字典列表，无结果返回空列表。

        用法:
            rows = mgr.fetchall(
                "SELECT * FROM sessions WHERE source = ? ORDER BY started_at DESC LIMIT ?",
                "cli", 20
            )
        """
        if self._needs_placeholder_conversion(self.db_type):
            sql = self._adapt_sql(sql, self.db_type)

        with self._connection() as conn:
            if self.db_type == DbType.POSTGRESQL:
                cursor = conn.cursor()
                cursor.execute(sql, params or ())
                rows = cursor.fetchall()
                cursor.close()
                if rows:
                    desc = [d[0] for d in cursor.description]
                    return [dict(zip(desc, r)) for r in rows]
                return []
            elif self.db_type == DbType.MYSQL:
                conn.execute(sql, params or ())
                return conn.fetchall()
            else:
                # SQLite
                cursor = conn.execute(sql, params or ())
                return [dict(r) for r in cursor.fetchall()]

    def execute_many(self, sql: str, params_list: List[tuple]) -> int:
        """
        批量执行写操作，返回总影响行数。

        用法:
            mgr.execute_many(
                "INSERT INTO sessions (id, source, started_at) VALUES (?, ?, ?)",
                [("id1", "cli", 123456), ("id2", "telegram", 123457)]
            )
        """
        if self._needs_placeholder_conversion(self.db_type):
            sql = self._adapt_sql(sql, self.db_type)

        total = 0
        with self._connection() as conn:
            if self.db_type == DbType.POSTGRESQL:
                cursor = conn.cursor()
                cursor.executemany(sql, params_list)
                total = cursor.rowcount
                cursor.close()
                conn.commit()
            elif self.db_type == DbType.MYSQL:
                conn.executemany(sql, params_list)
                total = conn.rowcount
            else:
                # SQLite
                conn.executemany(sql, params_list)
                total = conn.total_changes
        return total

    # ── 事务支持 ──────────────────────────────────────────────

    @contextmanager
    def transaction(self):
        """
        同步事务上下文管理器。

        用法:
            with mgr.transaction() as conn:
                conn.execute("INSERT INTO ...")
                conn.execute("UPDATE ...")
                # 自动 commit，异常时 rollback
        """
        conn = self._acquire()
        try:
            if self.db_type == DbType.SQLITE:
                conn.execute("BEGIN IMMEDIATE")
            elif self.db_type == DbType.POSTGRESQL:
                cursor = conn.cursor()
                cursor.execute("BEGIN")
                yield cursor
                conn.commit()
                cursor.close()
                return
            elif self.db_type == DbType.MYSQL:
                conn.start_transaction()

            yield conn

            if self.db_type == DbType.SQLITE:
                conn.commit()
            elif self.db_type == DbType.MYSQL:
                conn.commit()
        except Exception:
            if self.db_type == DbType.SQLITE:
                try:
                    conn.rollback()
                except Exception:
                    pass
            elif self.db_type == DbType.POSTGRESQL:
                try:
                    conn.rollback()
                except Exception:
                    pass
            elif self.db_type == DbType.MYSQL:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            self._release(conn)

    # ── 占位符转换 ─────────────────────────────────────────────

    @classmethod
    def _adapt_sql(cls, sql: str, db_type: DbType) -> str:
        """将 SQLite 特有语法转换为目标数据库语法"""
        if db_type == DbType.MYSQL:
            sql = sql.replace("INSERT OR IGNORE INTO", "INSERT IGNORE INTO")
            sql = sql.replace("INSERT OR REPLACE INTO", "REPLACE INTO")
            # ON CONFLICT(col) DO UPDATE SET ... → ON DUPLICATE KEY UPDATE ...
            sql = re.sub(
                r'ON\s+CONFLICT\s*\([^)]+\)\s*DO\s+UPDATE\s+SET',
                'ON DUPLICATE KEY UPDATE',
                sql,
                flags=re.IGNORECASE,
            )
            # excluded.col → VALUES(col)
            sql = re.sub(r'\bexcluded\.(\w+)', r'VALUES(\1)', sql)
            # Quote MySQL reserved words used as identifiers in Hermes
            sql = re.sub(r'(?<=\()key(?=\s*[,)])', '`key`', sql)
            sql = re.sub(r'\bkey\s*=\s*\?', '`key` = ?', sql)
        elif db_type == DbType.POSTGRESQL:
            if "INSERT OR IGNORE INTO" in sql:
                sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
                sql = sql.rstrip("; \t\n") + " ON CONFLICT DO NOTHING"
            if "INSERT OR REPLACE INTO" in sql:
                sql = sql.replace("INSERT OR REPLACE INTO", "INSERT INTO")
                sql = sql.rstrip("; \t\n") + " ON CONFLICT DO NOTHING"
        if cls._needs_placeholder_conversion(db_type):
            sql = cls._to_native_placeholders(sql)
        return sql

    @staticmethod
    def _to_native_placeholders(sql: str) -> str:
        """将 ? 占位符转换为数据库原生占位符（MySQL/PG 使用 %s）"""
        return sql.replace("?", "%s")

    @staticmethod
    def _needs_placeholder_conversion(db_type: DbType) -> bool:
        """MySQL 和 PostgreSQL 都需要将 ? 转换为 %s"""
        return db_type in (DbType.MYSQL, DbType.POSTGRESQL)


# ── 全局单例 ──────────────────────────────────────────────────

_manager: DatabaseManager = None
_manager_lock = threading.Lock()


def get_db_manager() -> DatabaseManager:
    """获取进程级数据库管理器单例（线程安全）"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = DatabaseManager()
    return _manager


def init_database() -> DatabaseManager:
    """初始化全局数据库管理器并返回"""
    mgr = get_db_manager()
    mgr.initialize()
    return mgr
