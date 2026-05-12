"""
数据迁移脚本：SQLite → MySQL/PostgreSQL 共享数据库。

将本地 ~/.hermes/state.db 中的会话数据迁移到共享数据库。

用法:
  python tools/migrate_sqlite_to_shared.py \
    --from /path/to/state.db \
    --to mysql://root:root@127.0.0.1:3306/hermes

  python tools/migrate_sqlite_to_shared.py \
    --from /path/to/state.db \
    --to postgresql://user:pass@127.0.0.1:5432/hermes

迁移内容:
  - sessions     → 会话记录
  - messages     → 对话历史
  - state_meta   → 键值元数据

不迁移的内容:
  - schema_version  → 共享 DB 有自己的版本管理
  - messages_fts(*) → FTS5 全文索引（SQLite 特有，共享 DB 用 LIKE 搜索）
  - 配置表          → 通过 Web UI 管理，无需从 SQLite 迁移

SQL 转换由 db/connection.py 的 _adapt_sql() 自动处理：
  - ? 占位符 → %s（MySQL/PG）
  - INSERT OR IGNORE → INSERT IGNORE（MySQL）/ INSERT ... ON CONFLICT DO NOTHING（PG）
  - key 列名 → `key`（MySQL 保留字引号）

作者: 清风
"""

import argparse
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# 确保能导入 hermes-agent 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("migrate")


def connect_sqlite(db_path: str) -> sqlite3.Connection:
    """连接源 SQLite 数据库"""
    if not Path(db_path).exists():
        logger.error("SQLite 文件不存在: %s", db_path)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


def init_target_db(db_type: str, db_url: str):
    """初始化目标共享数据库连接和 Schema"""
    os.environ["HERMES_DB_TYPE"] = db_type
    os.environ["HERMES_DB_URL"] = db_url

    # 清除缓存，强制重新检测
    import db.connection
    import importlib
    importlib.reload(db.connection)

    from db.connection import init_database
    from db.schema import init_schema

    db_mgr = init_database()
    init_schema(db_mgr)
    logger.info("目标数据库已连接并初始化 Schema")
    return db_mgr


def get_sqlite_row_count(conn: sqlite3.Connection, table: str) -> int:
    """获取 SQLite 表行数"""
    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
    return cursor.fetchone()[0]


def get_target_row_count(db_mgr, table: str) -> int:
    """获取目标表行数"""
    row = db_mgr.fetchone(f"SELECT COUNT(*) AS cnt FROM {table}")
    return row["cnt"] if row else 0


# ── 类型转换 ──────────────────────────────────────────────────────────

def _to_int_or_none(val) -> int | None:
    """将 SQLite 值转换为 int 或 None"""
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _to_float_or_none(val) -> float | None:
    """将 SQLite 值转换为 float 或 None"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ── 迁移函数 ──────────────────────────────────────────────────────────

def migrate_sessions(src_conn: sqlite3.Connection, db_mgr) -> int:
    """
    迁移 sessions 表。
    id 保持原样（TEXT → VARCHAR(36)）。
    时间戳: SQLite REAL 秒 → BIGINT 秒（两个系统都使用 time.time() 格式）。
    """
    columns = [
        "id", "source", "user_id", "model", "model_config", "system_prompt",
        "parent_session_id", "started_at", "ended_at", "end_reason",
        "message_count", "tool_call_count", "api_call_count",
        "input_tokens", "output_tokens", "cache_read_tokens",
        "cache_write_tokens", "reasoning_tokens",
        "billing_provider", "billing_base_url", "billing_mode",
        "estimated_cost_usd", "actual_cost_usd", "cost_status",
        "cost_source", "pricing_version", "title",
    ]

    rows = src_conn.execute(
        f"SELECT {', '.join(columns)} FROM sessions ORDER BY started_at"
    ).fetchall()

    if not rows:
        logger.info("sessions 表为空，跳过")
        return 0

    cols_str = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))
    # INSERT OR IGNORE 由 _adapt_sql 自动转换为各数据库方言
    sql = f"INSERT OR IGNORE INTO sessions ({cols_str}) VALUES ({placeholders})"

    params_list = []
    for row in rows:
        params = []
        for col in columns:
            val = row[col]
            if col in ("started_at", "ended_at") and val is not None:
                # SQLite REAL 秒 → BIGINT 秒
                val = int(float(val)) if isinstance(val, float) else int(val)
            elif col in ("message_count", "tool_call_count", "api_call_count",
                         "input_tokens", "output_tokens", "cache_read_tokens",
                         "cache_write_tokens", "reasoning_tokens"):
                val = _to_int_or_none(val)
            elif col in ("estimated_cost_usd", "actual_cost_usd"):
                val = _to_float_or_none(val)
            params.append(val)
        params_list.append(tuple(params))

    db_mgr.execute_many(sql, params_list)
    logger.info("sessions: %d 行已迁移", len(rows))
    return len(rows)


def migrate_messages(src_conn: sqlite3.Connection, db_mgr) -> int:
    """
    迁移 messages 表。
    保留原始 id（SQLite auto-increment → MySQL AUTO_INCREMENT/PG SERIAL）。
    时间戳: SQLite REAL 秒 → BIGINT 秒。
    """
    columns = [
        "id", "session_id", "role", "content", "tool_call_id", "tool_calls",
        "tool_name", "timestamp", "token_count", "finish_reason",
        "reasoning", "reasoning_content", "reasoning_details",
        "codex_reasoning_items", "codex_message_items",
    ]

    rows = src_conn.execute(
        f"SELECT {', '.join(columns)} FROM messages ORDER BY session_id, timestamp"
    ).fetchall()

    if not rows:
        logger.info("messages 表为空，跳过")
        return 0

    cols_str = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))
    sql = f"INSERT OR IGNORE INTO messages ({cols_str}) VALUES ({placeholders})"

    # 批量插入，每批 500 条
    batch_size = 500
    total = 0

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        params_list = []
        for row in batch:
            params = []
            for col in columns:
                val = row[col]
                if col == "timestamp" and val is not None:
                    # SQLite REAL 秒 → BIGINT 秒
                    val = int(float(val)) if isinstance(val, float) else int(val)
                elif col in ("id", "token_count"):
                    val = _to_int_or_none(val)
                params.append(val)
            params_list.append(tuple(params))

        db_mgr.execute_many(sql, params_list)
        total += len(batch)
        logger.info("messages: %d/%d 行已迁移", total, len(rows))

    logger.info("messages: 共 %d 行已迁移", total)
    return total


def migrate_state_meta(src_conn: sqlite3.Connection, db_mgr) -> int:
    """
    迁移 state_meta 表。
    key 列名由 _adapt_sql 自动处理（MySQL 用 `key`，PG/SQLite 用 key）。
    """
    rows = src_conn.execute(
        "SELECT key, value FROM state_meta"
    ).fetchall()

    if not rows:
        logger.info("state_meta 表为空，跳过")
        return 0

    sql = "INSERT OR IGNORE INTO state_meta (key, value) VALUES (?, ?)"

    params_list = [(row["key"], row["value"]) for row in rows]
    db_mgr.execute_many(sql, params_list)
    logger.info("state_meta: %d 行已迁移", len(rows))
    return len(rows)


# ── 主流程 ────────────────────────────────────────────────────────────

def run_migration(sqlite_path: str, db_type: str, db_url: str,
                  dry_run: bool = False) -> Dict[str, Any]:
    """
    执行完整迁移流程。
    返回统计信息字典。
    """
    stats: Dict[str, Any] = {
        "sessions": {"before": 0, "migrated": 0, "after": 0},
        "messages": {"before": 0, "migrated": 0, "after": 0},
        "state_meta": {"before": 0, "migrated": 0, "after": 0},
    }

    # 连接源数据库
    logger.info("连接 SQLite: %s", sqlite_path)
    src_conn = connect_sqlite(sqlite_path)

    # 统计源数据
    for table in stats:
        stats[table]["before"] = get_sqlite_row_count(src_conn, table)
    logger.info(
        "源数据: sessions=%d, messages=%d, state_meta=%d",
        stats["sessions"]["before"],
        stats["messages"]["before"],
        stats["state_meta"]["before"],
    )

    if dry_run:
        logger.info("--- 演练模式，不执行实际迁移 ---")
        src_conn.close()
        return stats

    # 连接目标数据库
    db_mgr = init_target_db(db_type, db_url)

    # 执行迁移（按依赖顺序：先 sessions，再 messages，最后 state_meta）
    start_time = time.time()

    logger.info("开始迁移 sessions...")
    stats["sessions"]["migrated"] = migrate_sessions(src_conn, db_mgr)

    logger.info("开始迁移 messages...")
    stats["messages"]["migrated"] = migrate_messages(src_conn, db_mgr)

    logger.info("开始迁移 state_meta...")
    stats["state_meta"]["migrated"] = migrate_state_meta(src_conn, db_mgr)

    elapsed = time.time() - start_time

    # 校验
    for table in stats:
        stats[table]["after"] = get_target_row_count(db_mgr, table)

    # 输出报告
    _print_report(stats, elapsed)

    # 清理
    src_conn.close()
    db_mgr.close()

    return stats


def _print_report(stats: Dict[str, Any], elapsed: float) -> None:
    """打印迁移报告"""
    print()
    print("=" * 60)
    print("  迁移报告")
    print("=" * 60)
    print(f"{'表名':<16} {'迁移前(源)':>10} {'迁移数':>10} {'迁移后(目标)':>12} {'状态':>8}")
    print("-" * 60)

    all_ok = True
    for table, s in stats.items():
        src_before = s["before"]
        migrated = s["migrated"]
        dst_after = s["after"]
        # 目标表可能已有数据（之前迁移过），after >= migrated 即正常
        status = "OK" if dst_after >= migrated and migrated == src_before else "CHECK"
        if status != "OK":
            all_ok = False
        print(f"{table:<16} {src_before:>10} {migrated:>10} {dst_after:>12} {status:>8}")

    print("-" * 60)
    print(f"耗时: {elapsed:.2f} 秒")
    if all_ok:
        print("状态: 全部迁移成功")
    else:
        print("状态: 部分表行数不一致，请检查（目标表可能有预存数据）")
    print("=" * 60)


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Hermes 数据迁移工具：SQLite → 共享数据库（MySQL/PostgreSQL）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --from ~/.hermes/state.db --to mysql://root:root@127.0.0.1:3306/hermes
  %(prog)s --from ~/.hermes/state.db --to postgresql://user:pass@127.0.0.1:5432/hermes
  %(prog)s --from ~/.hermes/state.db --to mysql://root:root@127.0.0.1:3306/hermes --dry-run
        """,
    )

    parser.add_argument(
        "--from", dest="from_path", required=True,
        help="源 SQLite 数据库文件路径（如 ~/.hermes/state.db）",
    )
    parser.add_argument(
        "--to", dest="to_url", required=True,
        help="目标数据库连接 URL（mysql:// 或 postgresql:// 开头）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="演练模式，只统计不实际迁移",
    )

    args = parser.parse_args()

    # 解析目标数据库类型
    to_url = args.to_url
    if to_url.startswith("mysql://"):
        db_type = "mysql"
    elif to_url.startswith("postgresql://") or to_url.startswith("postgres://"):
        db_type = "postgresql"
    else:
        logger.error("目标 URL 必须以 mysql:// 或 postgresql:// 开头")
        sys.exit(1)

    # 展开 ~ 路径
    from_path = os.path.expanduser(args.from_path)

    run_migration(from_path, db_type, to_url, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
