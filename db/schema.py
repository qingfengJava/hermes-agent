"""
数据库 Schema 定义与初始化。

包含所有表的 DDL 定义，同时兼容 MySQL 和 PostgreSQL。
通过 DialectHelper 处理跨库语法差异。

用法:
    from db.schema import init_schema
    init_schema(db_manager)
"""

from typing import List

from db.connection import DatabaseManager
from db.dialect import DbType, DialectHelper


def init_schema(db: DatabaseManager, profile_name: str = "default") -> None:
    """
    初始化数据库 Schema。

    幂等操作——所有 CREATE TABLE 使用 IF NOT EXISTS。
    缺少的列由 migrate_columns() 自动补充。

    参数:
        db: 已初始化的 DatabaseManager
        profile_name: 默认 Profile 名称
    """
    dialect = db.dialect
    db_type = db.db_type

    # 执行建表语句
    for sql in _build_all_tables(dialect, db_type):
        try:
            db.execute(sql)
        except Exception as e:
            err_msg = str(e)
            # MySQL 8.0.19 不支持 CREATE INDEX IF NOT EXISTS，索引已存在时报 1061
            # PG 报 42P07 (relation already exists)，SQLite 报 "already exists"
            if _is_duplicate_index_error(db_type, err_msg):
                pass
            else:
                import logging
                logging.getLogger(__name__).warning("Schema DDL skipped: %s", e)

    # 插入默认 Profile 配置
    _init_default_configs(db, profile_name)


def _is_duplicate_index_error(db_type: DbType, err_msg: str) -> bool:
    """判断错误是否由索引/表已存在引起"""
    if db_type == DbType.MYSQL:
        return "1061" in err_msg or "Duplicate key name" in err_msg
    elif db_type == DbType.POSTGRESQL:
        return "42P07" in err_msg or "already exists" in err_msg.lower()
    else:
        return "already exists" in err_msg.lower()


def _idx(name: str, table: str, cols: str, db_type: DbType) -> str:
    """生成跨库兼容的 CREATE INDEX 语句（MySQL 8.0.19 不支持 IF NOT EXISTS）"""
    if db_type == DbType.MYSQL:
        return f"CREATE INDEX {name} ON {table}({cols})"
    return f"CREATE INDEX IF NOT EXISTS {name} ON {table}({cols})"


def _uidx(name: str, table: str, cols: str, db_type: DbType) -> str:
    """生成跨库兼容的 CREATE UNIQUE INDEX 语句"""
    if db_type == DbType.MYSQL:
        return f"CREATE UNIQUE INDEX {name} ON {table}({cols})"
    return f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table}({cols})"


def _build_all_tables(dialect: DialectHelper, db_type: DbType) -> List[str]:
    """构建所有表的 CREATE TABLE 语句"""
    tables = []

    # ── 核心运行时表 ──

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS sessions (
            id VARCHAR(36) PRIMARY KEY,
            source VARCHAR(32) NOT NULL,
            user_id VARCHAR(128),
            model VARCHAR(128),
            model_config JSON,
            system_prompt TEXT,
            parent_session_id VARCHAR(36),
            started_at BIGINT NOT NULL,
            ended_at BIGINT,
            end_reason VARCHAR(64),
            title VARCHAR(200),
            message_count INT DEFAULT 0,
            tool_call_count INT DEFAULT 0,
            api_call_count INT DEFAULT 0,
            input_tokens BIGINT DEFAULT 0,
            output_tokens BIGINT DEFAULT 0,
            cache_read_tokens BIGINT DEFAULT 0,
            cache_write_tokens BIGINT DEFAULT 0,
            reasoning_tokens BIGINT DEFAULT 0,
            billing_provider VARCHAR(64),
            billing_base_url VARCHAR(512),
            billing_mode VARCHAR(32),
            estimated_cost_usd DECIMAL(18,6),
            actual_cost_usd DECIMAL(18,6),
            cost_status VARCHAR(32),
            cost_source VARCHAR(64),
            pricing_version VARCHAR(32)
        )
    """)

    tables.append(_idx("idx_sessions_source", "sessions", "source", db_type))
    tables.append(_idx("idx_sessions_started", "sessions", "started_at", db_type))
    tables.append(_idx("idx_sessions_title", "sessions", "title", db_type))
    tables.append(_idx("idx_sessions_parent", "sessions", "parent_session_id", db_type))

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS messages (
            {dialect.auto_increment_clause()},
            session_id VARCHAR(36) NOT NULL,
            role VARCHAR(32) NOT NULL,
            content TEXT,
            tool_call_id VARCHAR(128),
            tool_calls JSON,
            tool_name VARCHAR(128),
            timestamp BIGINT NOT NULL,
            token_count INT,
            finish_reason VARCHAR(32),
            reasoning TEXT,
            reasoning_content TEXT,
            reasoning_details TEXT,
            codex_reasoning_items TEXT,
            codex_message_items TEXT
        )
    """)

    tables.append(_idx("idx_messages_session", "messages", "session_id, timestamp", db_type))
    # MySQL 使用前缀索引
    if db_type == DbType.MYSQL:
        tables.append(_idx("idx_messages_content", "messages", "content(255)", db_type))
    else:
        tables.append(_idx("idx_messages_content", "messages", "content", db_type))

    key_col = "`key`" if db_type == DbType.MYSQL else "key"
    tables.append(f"""
        CREATE TABLE IF NOT EXISTS state_meta (
            {key_col} VARCHAR(128) PRIMARY KEY,
            value TEXT
        )
    """)

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS telegram_dm_topic_mode (
            chat_id VARCHAR(64) PRIMARY KEY,
            mode VARCHAR(16) NOT NULL
        )
    """)

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS telegram_dm_topic_bindings (
            chat_id VARCHAR(64),
            thread_id VARCHAR(64),
            session_id VARCHAR(36) NOT NULL,
            PRIMARY KEY (chat_id, thread_id)
        )
    """)

    # ── 配置表 ──

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS model_configs (
            id BIGINT PRIMARY KEY,
            profile_name VARCHAR(64) DEFAULT 'default',
            model_name VARCHAR(256) NOT NULL,
            provider_key VARCHAR(64),
            max_tokens INT DEFAULT 4096,
            temperature DECIMAL(4,2),
            top_p DECIMAL(4,2),
            is_default TINYINT DEFAULT 0,
            enabled TINYINT DEFAULT 1,
            created_at BIGINT,
            updated_at BIGINT
        )
    """)
    tables.append(_idx("idx_model_configs_profile", "model_configs", "profile_name", db_type))

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS provider_configs (
            id BIGINT PRIMARY KEY,
            profile_name VARCHAR(64) DEFAULT 'default',
            provider_key VARCHAR(64) NOT NULL,
            display_name VARCHAR(128),
            api_mode VARCHAR(32) NOT NULL,
            base_url VARCHAR(512),
            auth_type VARCHAR(32) DEFAULT 'api_key',
            env_var_name VARCHAR(64),
            extra_body JSON,
            extra_headers JSON,
            enabled TINYINT DEFAULT 1,
            metadata JSON,
            created_at BIGINT,
            updated_at BIGINT
        )
    """)
    tables.append(_uidx("idx_provider_key", "provider_configs", "profile_name, provider_key", db_type))

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS toolset_configs (
            id BIGINT PRIMARY KEY,
            profile_name VARCHAR(64) DEFAULT 'default',
            platform VARCHAR(32) NOT NULL,
            toolset_name VARCHAR(64) NOT NULL,
            enabled TINYINT DEFAULT 1,
            created_at BIGINT,
            updated_at BIGINT
        )
    """)
    tables.append(_uidx("idx_toolset_cfg", "toolset_configs", "profile_name, platform, toolset_name", db_type))

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS skill_configs (
            id BIGINT PRIMARY KEY,
            profile_name VARCHAR(64) DEFAULT 'default',
            skill_path VARCHAR(256) NOT NULL,
            platform VARCHAR(32) DEFAULT 'all',
            enabled TINYINT DEFAULT 1,
            pinned TINYINT DEFAULT 0,
            created_at BIGINT,
            updated_at BIGINT
        )
    """)
    tables.append(_uidx("idx_skill_cfg", "skill_configs", "profile_name, skill_path, platform", db_type))

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS platform_configs (
            id BIGINT PRIMARY KEY,
            profile_name VARCHAR(64) DEFAULT 'default',
            platform VARCHAR(32) NOT NULL,
            config_key VARCHAR(64) NOT NULL,
            config_value TEXT,
            is_secret TINYINT DEFAULT 0,
            created_at BIGINT,
            updated_at BIGINT
        )
    """)
    tables.append(_uidx("idx_platform_cfg", "platform_configs", "profile_name, platform, config_key", db_type))

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS agent_settings (
            id BIGINT PRIMARY KEY,
            profile_name VARCHAR(64) DEFAULT 'default',
            setting_key VARCHAR(64) NOT NULL,
            setting_value TEXT,
            created_at BIGINT,
            updated_at BIGINT
        )
    """)
    tables.append(_uidx("idx_agent_setting", "agent_settings", "profile_name, setting_key", db_type))

    # ── 业务扩展表 ──

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS token_usage (
            id BIGINT PRIMARY KEY,
            session_id VARCHAR(36) NOT NULL,
            profile_name VARCHAR(64) DEFAULT 'default',
            model VARCHAR(128),
            input_tokens INT DEFAULT 0,
            output_tokens INT DEFAULT 0,
            cache_tokens INT DEFAULT 0,
            reasoning_tokens INT DEFAULT 0,
            recorded_at BIGINT NOT NULL
        )
    """)
    tables.append(_idx("idx_usage_session", "token_usage", "session_id", db_type))
    tables.append(_idx("idx_usage_profile_time", "token_usage", "profile_name, recorded_at", db_type))

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS model_context_overrides (
            id BIGINT PRIMARY KEY,
            provider VARCHAR(64) NOT NULL,
            model VARCHAR(128) NOT NULL,
            context_limit INT NOT NULL,
            updated_at BIGINT
        )
    """)
    tables.append(_uidx("idx_ctx_override", "model_context_overrides", "provider, model", db_type))

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS cron_jobs (
            id BIGINT PRIMARY KEY,
            profile_name VARCHAR(64) DEFAULT 'default',
            name VARCHAR(200),
            schedule VARCHAR(100) NOT NULL,
            command TEXT NOT NULL,
            enabled TINYINT DEFAULT 1,
            paused TINYINT DEFAULT 0,
            last_run_at BIGINT,
            next_run_at BIGINT,
            created_at BIGINT,
            updated_at BIGINT
        )
    """)
    tables.append(_idx("idx_cron_profile", "cron_jobs", "profile_name", db_type))

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS cron_job_history (
            id BIGINT PRIMARY KEY,
            job_id BIGINT NOT NULL,
            run_at BIGINT NOT NULL,
            status VARCHAR(32) DEFAULT 'running',
            output_file VARCHAR(256),
            error_message TEXT,
            duration_ms INT,
            created_at BIGINT
        )
    """)
    tables.append(_idx("idx_cron_history_job", "cron_job_history", "job_id, run_at", db_type))

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS kanban_tasks (
            id BIGINT PRIMARY KEY,
            profile_name VARCHAR(64) DEFAULT 'default',
            title VARCHAR(500) NOT NULL,
            description TEXT,
            status VARCHAR(32) DEFAULT 'todo',
            assignee VARCHAR(64),
            priority VARCHAR(16) DEFAULT 'medium',
            session_id VARCHAR(36),
            blocked_reason TEXT,
            completed_at BIGINT,
            created_at BIGINT,
            updated_at BIGINT
        )
    """)
    tables.append(_idx("idx_kanban_status", "kanban_tasks", "profile_name, status", db_type))
    tables.append(_idx("idx_kanban_assignee", "kanban_tasks", "assignee", db_type))

    # ── 用户认证表 ──

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username VARCHAR(64) NOT NULL UNIQUE,
            password_hash VARCHAR(256) NOT NULL,
            role VARCHAR(32) DEFAULT 'admin',
            enabled TINYINT DEFAULT 1,
            last_login_at BIGINT,
            created_at BIGINT,
            updated_at BIGINT
        )
    """)

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id BIGINT PRIMARY KEY,
            user_id BIGINT NOT NULL,
            token VARCHAR(256) NOT NULL UNIQUE,
            expires_at BIGINT NOT NULL,
            created_at BIGINT
        )
    """)
    tables.append(_idx("idx_auth_token", "auth_tokens", "token", db_type))

    tables.append(f"""
        CREATE TABLE IF NOT EXISTS login_attempts (
            id BIGINT PRIMARY KEY,
            ip_address VARCHAR(64) NOT NULL,
            attempt_type VARCHAR(32) DEFAULT 'login',
            attempt_count INT DEFAULT 0,
            locked_until BIGINT,
            updated_at BIGINT
        )
    """)
    tables.append(_uidx("idx_login_ip_type", "login_attempts", "ip_address, attempt_type", db_type))

    return tables


def _init_default_configs(db: DatabaseManager, profile_name: str) -> None:
    """插入默认配置数据（幂等，跨库兼容）"""
    from db.id_generator import get_id_generator
    id_gen = get_id_generator()
    now = int(__import__("time").time() * 1000)
    dialect = db.dialect
    columns = ["id", "profile_name", "setting_key", "setting_value", "created_at", "updated_at"]

    # 默认 Agent 设置
    defaults = [
        ("memory_enabled", "true"),
        ("user_profile_enabled", "true"),
        ("memory_char_limit", "2200"),
        ("user_char_limit", "1375"),
        ("max_iterations", "90"),
    ]

    for key, value in defaults:
        # 使用方言化的 INSERT OR IGNORE，而非硬编码 SQLite 语法
        params = (id_gen.next_id(), profile_name, key, value, now, now)
        sql = _build_insert_or_ignore(db, "agent_settings", columns)
        # 先检查是否存在，避免不同方言 ON CONFLICT 兼容问题
        existing = db.fetchone(
            "SELECT 1 FROM agent_settings WHERE profile_name = ? AND setting_key = ?",
            profile_name, key,
        )
        if not existing:
            db.execute(sql, *params)


def _build_insert_or_ignore(db: DatabaseManager, table: str, columns: list) -> str:
    """构建跨库 INSERT OR IGNORE 语句"""
    dialect = db.dialect
    if db.db_type == DbType.POSTGRESQL:
        cols = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))
        return f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING"
    elif db.db_type == DbType.MYSQL:
        cols = ", ".join(columns)
        placeholders = ", ".join(["?"] * len(columns))
        return f"INSERT IGNORE INTO {table} ({cols}) VALUES ({placeholders})"
    else:
        cols = ", ".join(columns)
        placeholders = ", ".join(["?"] * len(columns))
        return f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})"
