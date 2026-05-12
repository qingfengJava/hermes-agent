"""
从共享数据库加载配置，映射为 config dict 格式。

当 HERMES_DB_TYPE 设置为 mysql/postgresql 时，此模块从数据库的配置表
读取数据并返回可与 DEFAULT_CONFIG 深度合并的覆盖字典。

映射关系：
  agent_settings    → memory.* / agent.* 等
  model_configs     → model（默认模型名称）
  provider_configs  → providers（provider 定义字典）
  toolset_configs   → toolsets / agent.disabled_toolsets
  skill_configs     → skills 配置
  platform_configs  → telegram.* / discord.* 等平台配置
"""

import os
from typing import Any, Dict, List, Optional


def _detect_shared_db() -> bool:
    """检测是否启用共享数据库模式"""
    db_type = os.environ.get("HERMES_DB_TYPE", "sqlite").lower()
    return db_type in ("mysql", "postgresql", "postgres", "pg")


def load_db_overrides(profile_name: str = "default") -> Dict[str, Any]:
    """
    从共享数据库加载配置覆盖。

    仅在共享数据库模式下执行，SQLite 模式下返回空字典。
    返回的字典结构与 DEFAULT_CONFIG 兼容，可直接深度合并。

    参数:
        profile_name: Profile 名称，默认 "default"
    """
    if not _detect_shared_db():
        return {}

    try:
        from db.connection import get_db_manager
        db_mgr = get_db_manager()
        db_mgr.initialize()
    except Exception:
        return {}

    overrides: Dict[str, Any] = {}

    # 按顺序加载各配置表
    _load_agent_settings(db_mgr, profile_name, overrides)
    _load_model_configs(db_mgr, profile_name, overrides)
    _load_provider_configs(db_mgr, profile_name, overrides)
    _load_toolset_configs(db_mgr, profile_name, overrides)
    _load_skill_configs(db_mgr, profile_name, overrides)
    _load_platform_configs(db_mgr, profile_name, overrides)

    return overrides


def _load_agent_settings(db_mgr, profile_name: str, overrides: Dict[str, Any]) -> None:
    """
    从 agent_settings 表加载配置。

    映射规则（setting_key → config 路径）:
      memory_enabled        → memory.memory_enabled
      user_profile_enabled  → memory.user_profile_enabled
      memory_char_limit     → memory.memory_char_limit
      user_char_limit       → memory.user_char_limit
      max_iterations        → agent.max_turns
    """
    rows = db_mgr.fetchall(
        "SELECT setting_key, setting_value FROM agent_settings "
        "WHERE profile_name = %s",
        profile_name,
    )
    if not rows:
        return

    # setting_key → (config_section, config_key, value_converter)
    key_mapping = {
        "memory_enabled":        ("memory", "memory_enabled", _to_bool),
        "user_profile_enabled":  ("memory", "user_profile_enabled", _to_bool),
        "memory_char_limit":     ("memory", "memory_char_limit", _to_int),
        "user_char_limit":       ("memory", "user_char_limit", _to_int),
        "max_iterations":        ("agent", "max_turns", _to_int),
    }

    for row in rows:
        key = row.get("setting_key", "")
        value = row.get("setting_value", "")
        if key in key_mapping:
            section, config_key, converter = key_mapping[key]
            if section not in overrides:
                overrides[section] = {}
            overrides[section][config_key] = converter(value)


def _load_model_configs(db_mgr, profile_name: str, overrides: Dict[str, Any]) -> None:
    """
    从 model_configs 表加载默认模型配置。

    默认模型选择规则：is_default=1 且 enabled=1，否则取第一个 enabled 的模型。
    映射规则:
      model_name → model（顶级配置键）
    """
    # 优先取标记为默认的模型
    row = db_mgr.fetchone(
        "SELECT model_name FROM model_configs "
        "WHERE profile_name = %s AND is_default = 1 AND enabled = 1 "
        "LIMIT 1",
        profile_name,
    )
    # 回退：取第一个启用的模型
    if not row:
        row = db_mgr.fetchone(
            "SELECT model_name FROM model_configs "
            "WHERE profile_name = %s AND enabled = 1 "
            "ORDER BY id LIMIT 1",
            profile_name,
        )

    if row and row.get("model_name"):
        overrides["model"] = row["model_name"]


def _load_provider_configs(db_mgr, profile_name: str, overrides: Dict[str, Any]) -> None:
    """
    从 provider_configs 表加载供应商配置。

    DB 表结构:
      provider_key, display_name, api_mode, base_url, auth_type,
      env_var_name, extra_body, extra_headers, enabled, metadata

    映射为目标格式:
      providers:
        {provider_key}:
          name: display_name
          base_url: base_url
          key_env: env_var_name
          api_mode: api_mode
          ...
    """
    rows = db_mgr.fetchall(
        "SELECT * FROM provider_configs "
        "WHERE profile_name = %s AND enabled = 1",
        profile_name,
    )
    if not rows:
        return

    providers = {}
    for row in rows:
        provider_key = row.get("provider_key", "")
        if not provider_key:
            continue

        provider_entry: Dict[str, Any] = {}

        if row.get("display_name"):
            provider_entry["name"] = row["display_name"]
        if row.get("base_url"):
            provider_entry["base_url"] = row["base_url"]
        if row.get("api_mode"):
            provider_entry["api_mode"] = row["api_mode"]
        if row.get("env_var_name"):
            provider_entry["key_env"] = row["env_var_name"]
        if row.get("auth_type"):
            provider_entry["auth_type"] = row["auth_type"]

        # 解析 JSON 字段
        extra_body = _parse_json(row.get("extra_body"))
        if extra_body:
            provider_entry["extra_body"] = extra_body
        extra_headers = _parse_json(row.get("extra_headers"))
        if extra_headers:
            provider_entry["extra_headers"] = extra_headers
        metadata = _parse_json(row.get("metadata"))
        if metadata:
            provider_entry["metadata"] = metadata

        providers[provider_key] = provider_entry

    if providers:
        overrides["providers"] = providers


def _load_toolset_configs(db_mgr, profile_name: str, overrides: Dict[str, Any]) -> None:
    """
    从 toolset_configs 表加载工具集启用/禁用配置。

    映射规则:
      enabled=1 & platform='cli' → toolsets 列表
      enabled=0 & platform='cli' → agent.disabled_toolsets 列表
    """
    rows = db_mgr.fetchall(
        "SELECT toolset_name, enabled, platform FROM toolset_configs "
        "WHERE profile_name = %s",
        profile_name,
    )
    if not rows:
        return

    enabled_toolsets: List[str] = []
    disabled_toolsets: List[str] = []

    for row in rows:
        toolset_name = row.get("toolset_name", "")
        if not toolset_name:
            continue
        is_enabled = _to_bool(row.get("enabled", 1))
        if is_enabled:
            if toolset_name not in enabled_toolsets:
                enabled_toolsets.append(toolset_name)
        else:
            if toolset_name not in disabled_toolsets:
                disabled_toolsets.append(toolset_name)

    if enabled_toolsets:
        overrides["toolsets"] = enabled_toolsets
    if disabled_toolsets:
        if "agent" not in overrides:
            overrides["agent"] = {}
        overrides["agent"]["disabled_toolsets"] = disabled_toolsets


def _load_skill_configs(db_mgr, profile_name: str, overrides: Dict[str, Any]) -> None:
    """
    从 skill_configs 表加载技能启用/置顶配置。

    映射规则:
      enabled=0 → skills.disabled 列表（skill_path）
      pinned=1  → skills.pinned 列表（skill_path）
    """
    rows = db_mgr.fetchall(
        "SELECT skill_path, enabled, pinned FROM skill_configs "
        "WHERE profile_name = %s",
        profile_name,
    )
    if not rows:
        return

    disabled_skills: List[str] = []
    pinned_skills: List[str] = []

    for row in rows:
        skill_path = row.get("skill_path", "")
        if not skill_path:
            continue
        if not _to_bool(row.get("enabled", 1)):
            disabled_skills.append(skill_path)
        if _to_bool(row.get("pinned", 0)):
            pinned_skills.append(skill_path)

    skills_override: Dict[str, Any] = {}
    if disabled_skills:
        skills_override["disabled"] = disabled_skills
    if pinned_skills:
        skills_override["pinned"] = pinned_skills

    if skills_override:
        overrides["skills"] = skills_override


def _load_platform_configs(db_mgr, profile_name: str, overrides: Dict[str, Any]) -> None:
    """
    从 platform_configs 表加载平台配置。

    映射规则:
      platform = 'telegram' & config_key = 'bot_token' → telegram.bot_token
      platform = 'discord'  & config_key = 'bot_token'  → discord.bot_token
      通用: {platform}.{config_key} = config_value

    加密字段（is_secret=1）不会加载到配置中，而是从环境变量读取。
    """
    rows = db_mgr.fetchall(
        "SELECT platform, config_key, config_value, is_secret FROM platform_configs "
        "WHERE profile_name = %s AND is_secret = 0",
        profile_name,
    )
    if not rows:
        return

    for row in rows:
        platform = row.get("platform", "")
        config_key = row.get("config_key", "")
        config_value = row.get("config_value", "")
        if not platform or not config_key or config_value is None:
            continue

        if platform not in overrides:
            overrides[platform] = {}
        overrides[platform][config_key] = _coerce_value(config_value)


# ── 辅助函数 ──────────────────────────────────────────────────────────

def _to_bool(value) -> bool:
    """将数据库中的值转换为 Python bool"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    return False


def _to_int(value) -> int:
    """将数据库中的值转换为 Python int"""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _coerce_value(value: str) -> Any:
    """智能类型转换：尝试解析为 bool/int/float，否则保留字符串"""
    if not isinstance(value, str):
        return value
    # bool
    lower = value.lower()
    if lower in ("true", "false"):
        return lower == "true"
    # int
    try:
        return int(value)
    except ValueError:
        pass
    # float
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _parse_json(value) -> Optional[Any]:
    """安全解析 JSON 字符串"""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value.strip():
        import json
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    return None
