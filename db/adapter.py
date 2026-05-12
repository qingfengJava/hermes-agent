"""
数据库后端适配器。

将 DatabaseManager 包装为与 sqlite3.Connection 兼容的接口，
使得 SessionDB 的现有代码可以在不修改业务逻辑的情况下
切换到 PostgreSQL/MySQL。
"""

import json
import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RowAdapter(dict):
    """
    兼容 sqlite3.Row 的行适配器。

    支持 dict 式访问 row["key"] 和索引访问 row[0]。
    对于 isinstance(row, sqlite3.Row) 检查，调用方应改为
    使用 hasattr(row, "keys") 或直接使用 dict 访问。
    """

    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)
        # 维护一份索引映射，使 row[0] 可以工作
        self._keys = list(data.keys()) if data else []

    def __getitem__(self, key):
        # 整数 key → 按索引访问
        if isinstance(key, (int,)):
            k = self._keys[key]
            return super().__getitem__(k)
        return super().__getitem__(key)


class CursorAdapter:
    """
    兼容 sqlite3.Cursor 的光标适配器。
    """

    def __init__(self, rows: List[Dict[str, Any]], rowcount: int = 0,
                 lastrowid: Optional[int] = None, description: List = None):
        self._rows = [RowAdapter(r) if not isinstance(r, RowAdapter) else r
                      for r in (rows or [])]
        self._index = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self.description = description or []

    def fetchone(self):
        """返回下一行，无更多行时返回 None"""
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self):
        """返回所有剩余行"""
        remaining = self._rows[self._index:]
        self._index = len(self._rows)
        return remaining

    def __iter__(self):
        return iter(self._rows)


class ConnectionAdapter:
    """
    兼容 sqlite3.Connection 的连接适配器。

    将 DatabaseManager 的同步接口映射为 sqlite3.Connection 风格。
    在共享数据库模式下替换 SessionDB 中的 self._conn。

    用法:
        db_mgr = get_db_manager()
        db_mgr.initialize()
        conn = ConnectionAdapter(db_mgr)
        cursor = conn.execute("SELECT * FROM sessions WHERE id = ?", sid)
        row = cursor.fetchone()
    """

    def __init__(self, db_mgr):
        """
        参数:
            db_mgr: 已初始化的 DatabaseManager 实例
        """
        self._db = db_mgr
        # 兼容 SessionDB._conn 上的一些属性访问
        self._row_factory = None

    # ── 核心方法 ──────────────────────────────────────────

    def execute(self, sql: str, params=()) -> CursorAdapter:
        """
        执行 SQL 语句。

        SELECT → 返回带结果的 CursorAdapter
        INSERT/UPDATE/DELETE → 返回带 rowcount 的 CursorAdapter
        """
        sql = sql.strip()
        # 将元组参数转换为位置参数列表
        if params:
            if isinstance(params, (list, tuple)):
                param_args = tuple(params)
            else:
                param_args = (params,)
        else:
            param_args = ()

        upper = sql[:12].upper()

        if upper.startswith("SELECT") or upper.startswith("WITH") or upper.startswith("PRAGMA"):
            # 查询 —— 返回结果集
            rows = self._db.fetchall(sql, *param_args)
            return CursorAdapter(rows)
        else:
            # 写操作 —— 返回 rowcount 和 lastrowid
            rowcount = self._db.execute(sql, *param_args)
            # 对于 INSERT，尝试获取 lastrowid
            lastrowid = None
            if upper.startswith("INSERT"):
                try:
                    # 查询最后插入的 ID（使用方言化的 last_insert_id）
                    row = self._db.fetchone("SELECT last_insert_rowid()" if self._db.db_type.value == "sqlite"
                                            else "SELECT LASTVAL()" if self._db.db_type.value == "postgresql"
                                            else "SELECT LAST_INSERT_ID()")
                    if row:
                        lastrowid = list(row.values())[0]
                except Exception:
                    pass
            return CursorAdapter([], rowcount=rowcount, lastrowid=lastrowid)

    def executescript(self, sql: str) -> CursorAdapter:
        """
        执行多语句脚本（以 ; 分隔）。

        用于 CREATE TABLE、schema migration 等场景。
        """
        # 按 ; 分割并逐条执行
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for stmt in statements:
            try:
                self._db.execute(stmt)
            except Exception as e:
                logger.debug("executescript statement skipped: %s", e)
        return CursorAdapter([], rowcount=len(statements))

    def commit(self) -> None:
        """提交事务。共享数据库模式下为 no-op（自动提交）。"""
        pass

    def rollback(self) -> None:
        """回滚事务。共享数据库模式下为 no-op。"""
        pass

    def close(self) -> None:
        """关闭连接。由 DatabaseManager 管理生命周期，此处为 no-op。"""
        pass

    # ── PRAGMA 兼容 ──────────────────────────────────────

    def execute_pragma(self, pragma_sql: str, params=()) -> Optional[Any]:
        """
        处理 PRAGMA 语句（SQLite 特有）。
        在共享数据库模式下静默忽略。
        """
        # journal_mode=WAL, foreign_keys=ON 等在共享 DB 中不适用
        upper = pragma_sql.upper()
        if "JOURNAL_MODE" in upper or "FOREIGN_KEYS" in upper:
            return "wal"  # 返回兼容值
        if "WAL_CHECKPOINT" in upper:
            return [0, 0, 0]  # 模拟成功
        if "TABLE_INFO" in upper:
            # 从 information_schema 获取列信息
            return self._get_table_info(pragma_sql)
        return None

    def _get_table_info(self, pragma_sql: str) -> List[tuple]:
        """获取表结构信息（模拟 PRAGMA table_info）"""
        import re
        match = re.search(r'table_info\(["\']?(\w+)["\']?\)', pragma_sql, re.IGNORECASE)
        if not match:
            return []
        table_name = match.group(1)
        try:
            rows = self._db.fetchall(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_name = ? "
                "ORDER BY ordinal_position",
                table_name,
            )
            result = []
            for i, r in enumerate(rows):
                col_name = list(r.values())[0]
                col_type = list(r.values())[1] if len(r) > 1 else "TEXT"
                nullable = list(r.values())[2] if len(r) > 2 else "YES"
                dflt = list(r.values())[3] if len(r) > 3 else None
                notnull = 1 if nullable == "NO" else 0
                pk = 1 if col_name == "id" else 0
                result.append((i, col_name, col_type, notnull, dflt, pk))
            return result
        except Exception:
            return []
