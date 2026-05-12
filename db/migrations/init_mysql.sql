-- ============================================================
-- Hermes 数据库初始化脚本 (MySQL)
-- ============================================================
-- 用法: mysql -u root -proot < init_hermes_db.sql
-- ============================================================

-- 创建数据库
CREATE DATABASE IF NOT EXISTS hermes
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE hermes;

-- ============================================================
-- 1. 核心运行时表（Agent 主写，WebUI 主读）
-- ============================================================

-- 会话表
CREATE TABLE IF NOT EXISTS sessions (
    id              VARCHAR(36) PRIMARY KEY     COMMENT '会话唯一 ID（UUID 格式）',
    source          VARCHAR(32) NOT NULL        COMMENT '会话来源：cli/telegram/discord/slack/wechat/...',
    user_id         VARCHAR(128)                COMMENT '用户标识',
    model           VARCHAR(128)                COMMENT '使用的模型名称（如 openrouter/anthropic/claude-sonnet-4）',
    model_config    JSON                        COMMENT '模型参数快照',
    system_prompt   TEXT                        COMMENT '系统提示词完整快照',
    parent_session_id VARCHAR(36)               COMMENT '父会话 ID（压缩链/子代理/分支）',
    started_at      BIGINT NOT NULL             COMMENT '会话开始时间（Unix 毫秒）',
    ended_at        BIGINT                      COMMENT '会话结束时间（Unix 毫秒）',
    end_reason      VARCHAR(64)                 COMMENT '结束原因：user_ended/compression/session_reset/...',
    title           VARCHAR(200)                COMMENT '会话标题（≤100字符）',
    -- 统计计数
    message_count   INT DEFAULT 0               COMMENT '消息总数',
    tool_call_count INT DEFAULT 0               COMMENT '工具调用总次数',
    api_call_count  INT DEFAULT 0               COMMENT 'LLM API 调用次数',
    input_tokens    BIGINT DEFAULT 0            COMMENT '累计输入 Token',
    output_tokens   BIGINT DEFAULT 0            COMMENT '累计输出 Token',
    cache_read_tokens  BIGINT DEFAULT 0         COMMENT '缓存读取 Token',
    cache_write_tokens BIGINT DEFAULT 0         COMMENT '缓存写入 Token',
    reasoning_tokens   BIGINT DEFAULT 0         COMMENT '推理 Token',
    -- 费用追踪
    billing_provider VARCHAR(64)                COMMENT '计费供应商',
    billing_base_url VARCHAR(512)               COMMENT '计费 API 地址',
    billing_mode     VARCHAR(32)                COMMENT '计费模式',
    estimated_cost   DECIMAL(18,6)              COMMENT '预估费用（USD）',
    actual_cost      DECIMAL(18,6)              COMMENT '实际费用（USD）',
    cost_status      VARCHAR(32)                COMMENT '费用状态：estimated/actual/unknown',
    cost_source      VARCHAR(64)                COMMENT '费用数据来源',
    pricing_version  VARCHAR(32)                COMMENT '定价版本',
    INDEX idx_sessions_source (source),
    INDEX idx_sessions_started (started_at),
    INDEX idx_sessions_title (title),
    INDEX idx_sessions_parent (parent_session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='会话元数据表';


-- 消息表
CREATE TABLE IF NOT EXISTS messages (
    id              BIGINT PRIMARY KEY           COMMENT '消息唯一 ID（雪花算法生成）',
    session_id      VARCHAR(36) NOT NULL         COMMENT '所属会话 ID',
    role            VARCHAR(32) NOT NULL         COMMENT '消息角色：user/assistant/system/tool',
    content         TEXT                         COMMENT '消息内容（长文本支持）',
    tool_call_id    VARCHAR(128)                 COMMENT '工具调用 ID',
    tool_calls      JSON                         COMMENT '工具调用详情（JSON数组）',
    tool_name       VARCHAR(128)                 COMMENT '工具名称',
    timestamp       BIGINT NOT NULL              COMMENT '消息时间戳（Unix 毫秒）',
    token_count     INT                          COMMENT '此消息消耗 Token 数',
    finish_reason   VARCHAR(32)                 COMMENT '结束原因：stop/length/tool_calls/...',
    reasoning       TEXT                         COMMENT '推理过程文本',
    reasoning_content TEXT                       COMMENT '推理内容',
    reasoning_details TEXT                       COMMENT '推理详情（JSON）',
    codex_reasoning_items TEXT                  COMMENT 'Codex 推理项（JSON）',
    codex_message_items   TEXT                  COMMENT 'Codex 消息项（JSON）',
    INDEX idx_messages_session (session_id, timestamp),
    INDEX idx_messages_content (content(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='消息表';


-- 系统元数据 KV 表
CREATE TABLE IF NOT EXISTS system_meta (
    meta_key        VARCHAR(128) PRIMARY KEY     COMMENT '键',
    meta_value      TEXT                         COMMENT '值'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='系统元数据键值存储';


-- Telegram DM 主题模式
CREATE TABLE IF NOT EXISTS telegram_dm_topic_mode (
    chat_id         VARCHAR(64) PRIMARY KEY      COMMENT 'Telegram 聊天 ID',
    mode            VARCHAR(16) NOT NULL         COMMENT '模式：auto/manual'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Telegram DM 主题模式配置';


-- Telegram DM 主题绑定
CREATE TABLE IF NOT EXISTS telegram_dm_topic_bindings (
    chat_id         VARCHAR(64)                  COMMENT 'Telegram 聊天 ID',
    thread_id       VARCHAR(64)                  COMMENT 'Telegram 主题线程 ID',
    session_id      VARCHAR(36) NOT NULL         COMMENT '绑定的 Hermes 会话 ID',
    PRIMARY KEY (chat_id, thread_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Telegram DM 主题与会话绑定';


-- ============================================================
-- 2. 配置表（WebUI 管理，Agent 只读）
-- ============================================================

-- 模型配置
CREATE TABLE IF NOT EXISTS model_configs (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    profile_name    VARCHAR(64) DEFAULT 'default' COMMENT 'Profile 名称（多 Profile 支持）',
    model_name      VARCHAR(256) NOT NULL        COMMENT '模型全名（如 openrouter/anthropic/claude-sonnet-4）',
    provider_key    VARCHAR(64)                  COMMENT '关联供应商标识',
    max_tokens      INT DEFAULT 4096             COMMENT '最大输出 Token',
    temperature     DECIMAL(4,2)                 COMMENT '温度参数（0-2）',
    top_p           DECIMAL(4,2)                 COMMENT 'Top-P 采样参数',
    is_default      TINYINT DEFAULT 0            COMMENT '是否默认模型（0/1）',
    enabled         TINYINT DEFAULT 1            COMMENT '是否启用（0/1）',
    created_at      BIGINT                       COMMENT '创建时间（Unix 毫秒）',
    updated_at      BIGINT                       COMMENT '更新时间（Unix 毫秒）',
    INDEX idx_model_configs_profile (profile_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='模型配置表';


-- 供应商配置
CREATE TABLE IF NOT EXISTS provider_configs (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    profile_name    VARCHAR(64) DEFAULT 'default' COMMENT 'Profile 名称',
    provider_key    VARCHAR(64) NOT NULL         COMMENT '供应商唯一标识（如 openrouter/deepseek/anthropic）',
    display_name    VARCHAR(128)                 COMMENT '供应商显示名称',
    api_mode        VARCHAR(32) NOT NULL         COMMENT 'API 模式：chat_completions/anthropic_messages/codex_responses/bedrock_converse',
    base_url        VARCHAR(512)                 COMMENT 'API 基础地址',
    auth_type       VARCHAR(32) DEFAULT 'api_key' COMMENT '认证类型：api_key/oauth/none',
    env_var_name    VARCHAR(64)                  COMMENT '对应 .env 中的环境变量名',
    extra_body      JSON                         COMMENT '请求体额外参数',
    extra_headers   JSON                         COMMENT '请求头额外参数',
    enabled         TINYINT DEFAULT 1            COMMENT '是否启用（0/1）',
    metadata        JSON                         COMMENT '扩展元数据（context_window/pricing/capabilities）',
    created_at      BIGINT                       COMMENT '创建时间（Unix 毫秒）',
    updated_at      BIGINT                       COMMENT '更新时间（Unix 毫秒）',
    UNIQUE INDEX idx_provider_key (profile_name, provider_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='LLM 供应商配置表';


-- 工具集配置
CREATE TABLE IF NOT EXISTS toolset_configs (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    profile_name    VARCHAR(64) DEFAULT 'default' COMMENT 'Profile 名称',
    platform        VARCHAR(32) NOT NULL         COMMENT '平台：cli/telegram/discord/slack/...',
    toolset_name    VARCHAR(64) NOT NULL         COMMENT '工具集名称：web/browser/terminal/code_execution/...',
    enabled         TINYINT DEFAULT 1            COMMENT '是否启用（0/1）',
    created_at      BIGINT                       COMMENT '创建时间（Unix 毫秒）',
    updated_at      BIGINT                       COMMENT '更新时间（Unix 毫秒）',
    UNIQUE INDEX idx_toolset_cfg (profile_name, platform, toolset_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='工具集按平台配置表';


-- 技能配置
CREATE TABLE IF NOT EXISTS skill_configs (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    profile_name    VARCHAR(64) DEFAULT 'default' COMMENT 'Profile 名称',
    skill_path      VARCHAR(256) NOT NULL        COMMENT '技能路径（如 software-development/debugging）',
    platform        VARCHAR(32) DEFAULT 'all'    COMMENT '适用平台：all/telegram/cli/...',
    enabled         TINYINT DEFAULT 1            COMMENT '是否启用（0/1）',
    pinned          TINYINT DEFAULT 0            COMMENT '是否置顶（0/1）',
    created_at      BIGINT                       COMMENT '创建时间（Unix 毫秒）',
    updated_at      BIGINT                       COMMENT '更新时间（Unix 毫秒）',
    UNIQUE INDEX idx_skill_cfg (profile_name, skill_path, platform)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='技能开关配置表';


-- 平台通道配置
CREATE TABLE IF NOT EXISTS platform_configs (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    profile_name    VARCHAR(64) DEFAULT 'default' COMMENT 'Profile 名称',
    platform        VARCHAR(32) NOT NULL         COMMENT '平台标识：telegram/discord/slack/wechat/...',
    config_key      VARCHAR(64) NOT NULL         COMMENT '配置键：bot_token/enabled/webhook_url/...',
    config_value    TEXT                         COMMENT '配置值',
    is_secret       TINYINT DEFAULT 0            COMMENT '是否加密存储（0/1）',
    created_at      BIGINT                       COMMENT '创建时间（Unix 毫秒）',
    updated_at      BIGINT                       COMMENT '更新时间（Unix 毫秒）',
    UNIQUE INDEX idx_platform_cfg (profile_name, platform, config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='平台通道配置表';


-- Agent 行为设置
CREATE TABLE IF NOT EXISTS agent_settings (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    profile_name    VARCHAR(64) DEFAULT 'default' COMMENT 'Profile 名称',
    setting_key     VARCHAR(64) NOT NULL         COMMENT '设置键：max_iterations/memory_enabled/...',
    setting_value   TEXT                         COMMENT '设置值',
    created_at      BIGINT                       COMMENT '创建时间（Unix 毫秒）',
    updated_at      BIGINT                       COMMENT '更新时间（Unix 毫秒）',
    UNIQUE INDEX idx_agent_setting (profile_name, setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Agent 行为参数设置表';


-- ============================================================
-- 3. 业务扩展表（WebUI 管理，Agent 参与读写）
-- ============================================================

-- Token 用量明细
CREATE TABLE IF NOT EXISTS token_usage (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    session_id      VARCHAR(36) NOT NULL         COMMENT '会话 ID',
    profile_name    VARCHAR(64) DEFAULT 'default' COMMENT 'Profile 名称',
    model           VARCHAR(128)                 COMMENT '使用的模型',
    input_tokens    INT DEFAULT 0                COMMENT '输入 Token 数',
    output_tokens   INT DEFAULT 0                COMMENT '输出 Token 数',
    cache_tokens    INT DEFAULT 0                COMMENT '缓存 Token 数',
    reasoning_tokens INT DEFAULT 0               COMMENT '推理 Token 数',
    recorded_at     BIGINT NOT NULL              COMMENT '记录时间（Unix 毫秒）',
    INDEX idx_usage_session (session_id),
    INDEX idx_usage_profile_time (profile_name, recorded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Token用量明细表';


-- 模型上下文覆盖
CREATE TABLE IF NOT EXISTS model_context_overrides (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    provider        VARCHAR(64) NOT NULL         COMMENT '供应商标识',
    model           VARCHAR(128) NOT NULL        COMMENT '模型名称',
    context_limit   INT NOT NULL                 COMMENT '自定义上下文限制（Token数）',
    updated_at      BIGINT                       COMMENT '更新时间（Unix 毫秒）',
    UNIQUE INDEX idx_ctx_override (provider, model)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='模型上下文限制覆盖表';


-- 定时任务
CREATE TABLE IF NOT EXISTS cron_jobs (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    profile_name    VARCHAR(64) DEFAULT 'default' COMMENT 'Profile 名称',
    name            VARCHAR(200)                 COMMENT '任务名称',
    schedule        VARCHAR(100) NOT NULL        COMMENT 'Cron 表达式（如 "0 */6 * * *"）',
    command         TEXT NOT NULL                COMMENT '执行的命令/提示词',
    enabled         TINYINT DEFAULT 1            COMMENT '是否启用（0/1）',
    paused          TINYINT DEFAULT 0            COMMENT '是否暂停（0/1）',
    last_run_at     BIGINT                       COMMENT '上次执行时间（Unix 毫秒）',
    next_run_at     BIGINT                       COMMENT '下次执行时间（Unix 毫秒）',
    created_at      BIGINT                       COMMENT '创建时间（Unix 毫秒）',
    updated_at      BIGINT                       COMMENT '更新时间（Unix 毫秒）',
    INDEX idx_cron_profile (profile_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='定时任务表';


-- 定时任务执行历史
CREATE TABLE IF NOT EXISTS cron_job_history (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    job_id          BIGINT NOT NULL              COMMENT '关联的任务 ID',
    run_at          BIGINT NOT NULL              COMMENT '执行时间（Unix 毫秒）',
    status          VARCHAR(32) DEFAULT 'running' COMMENT '执行状态：running/completed/failed',
    output_file     VARCHAR(256)                 COMMENT '输出文件路径',
    error_message   TEXT                         COMMENT '错误信息',
    duration_ms     INT                          COMMENT '执行耗时（毫秒）',
    created_at      BIGINT                       COMMENT '创建时间（Unix 毫秒）',
    INDEX idx_cron_history_job (job_id, run_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='定时任务执行历史表';


-- Kanban 任务看板
CREATE TABLE IF NOT EXISTS kanban_tasks (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    profile_name    VARCHAR(64) DEFAULT 'default' COMMENT 'Profile 名称',
    title           VARCHAR(500) NOT NULL        COMMENT '任务标题',
    description     TEXT                         COMMENT '任务描述',
    status          VARCHAR(32) DEFAULT 'todo'   COMMENT '任务状态：triage/todo/ready/running/blocked/done/archived',
    assignee        VARCHAR(64)                  COMMENT '负责人',
    priority        VARCHAR(16) DEFAULT 'medium' COMMENT '优先级：low/medium/high/critical',
    session_id      VARCHAR(36)                  COMMENT '关联的 Hermes 会话 ID',
    blocked_reason  TEXT                         COMMENT '阻塞原因',
    completed_at    BIGINT                       COMMENT '完成时间（Unix 毫秒）',
    created_at      BIGINT                       COMMENT '创建时间（Unix 毫秒）',
    updated_at      BIGINT                       COMMENT '更新时间（Unix 毫秒）',
    INDEX idx_kanban_status (profile_name, status),
    INDEX idx_kanban_assignee (assignee)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Kanban任务看板表';


-- ============================================================
-- 4. 用户认证表（WebUI 专用）
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id              BIGINT PRIMARY KEY           COMMENT '用户 ID（雪花算法）',
    username        VARCHAR(64) NOT NULL         COMMENT '用户名',
    password_hash   VARCHAR(256) NOT NULL        COMMENT '密码哈希（BCrypt）',
    role            VARCHAR(32) DEFAULT 'admin'  COMMENT '角色：admin/user',
    enabled         TINYINT DEFAULT 1            COMMENT '是否启用（0/1）',
    last_login_at   BIGINT                       COMMENT '最后登录时间（Unix 毫秒）',
    created_at      BIGINT                       COMMENT '创建时间（Unix 毫秒）',
    updated_at      BIGINT                       COMMENT '更新时间（Unix 毫秒）',
    UNIQUE INDEX idx_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='用户认证表';


-- 认证令牌
CREATE TABLE IF NOT EXISTS auth_tokens (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    user_id         BIGINT NOT NULL              COMMENT '关联的用户 ID',
    token           VARCHAR(256) NOT NULL        COMMENT 'JWT 令牌',
    expires_at      BIGINT NOT NULL              COMMENT '过期时间（Unix 毫秒）',
    created_at      BIGINT                       COMMENT '创建时间（Unix 毫秒）',
    INDEX idx_auth_token (token)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='认证令牌表';


-- 登录限流
CREATE TABLE IF NOT EXISTS login_attempts (
    id              BIGINT PRIMARY KEY           COMMENT '主键 ID',
    ip_address      VARCHAR(64) NOT NULL         COMMENT 'IP 地址',
    attempt_type    VARCHAR(32) DEFAULT 'login'  COMMENT '尝试类型：login/token',
    attempt_count   INT DEFAULT 0                COMMENT '失败次数',
    locked_until    BIGINT                       COMMENT '锁定截止时间（Unix 毫秒）',
    updated_at      BIGINT                       COMMENT '更新时间（Unix 毫秒）',
    UNIQUE INDEX idx_login_ip_type (ip_address, attempt_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='登录限流表';


-- ============================================================
-- 5. 默认数据插入
-- ============================================================

-- 默认 Agent 行为参数
INSERT IGNORE INTO agent_settings (id, profile_name, setting_key, setting_value, created_at, updated_at) VALUES
    (10001, 'default', 'memory_enabled', 'true', UNIX_TIMESTAMP()*1000, UNIX_TIMESTAMP()*1000),
    (10002, 'default', 'user_profile_enabled', 'true', UNIX_TIMESTAMP()*1000, UNIX_TIMESTAMP()*1000),
    (10003, 'default', 'memory_char_limit', '2200', UNIX_TIMESTAMP()*1000, UNIX_TIMESTAMP()*1000),
    (10004, 'default', 'user_char_limit', '1375', UNIX_TIMESTAMP()*1000, UNIX_TIMESTAMP()*1000),
    (10005, 'default', 'max_iterations', '90', UNIX_TIMESTAMP()*1000, UNIX_TIMESTAMP()*1000);

-- 默认管理员用户（密码: admin123，BCrypt 加密）
-- 生产环境请立即修改！
INSERT IGNORE INTO users (id, username, password_hash, role, enabled, created_at, updated_at) VALUES
    (10001, 'admin', '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy', 'admin', 1, UNIX_TIMESTAMP()*1000, UNIX_TIMESTAMP()*1000);
