"""
将 ~/.hermes/config.yaml 中的配置数据迁移到共享数据库。

用法:
    python tools/migrate_config_yaml_to_db.py [--dry-run]

映射规则:
    model.default / model.provider  → model_configs 表（标记为默认+启用）
    platform_toolsets              → toolset_configs 表
    telegram.* / discord.* 等      → platform_configs 表（非加密字段）
    agent_settings                 → 已通过 _init_default_configs() 初始化，跳过
"""

import os
import sys
import time
from pathlib import Path

import yaml

# 添加 agent 目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hermes_constants import get_hermes_home
from db.id_generator import get_id_generator


# provider_key 映射（config.yaml model.provider → DB provider_key）
PROVIDER_BASE_URLS = {
    "alibaba": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta",
    "deepseek": "https://api.deepseek.com/v1",
    "xai": "https://api.x.ai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "groq": "https://api.groq.com/openai/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "together": "https://api.together.xyz/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

PROVIDER_DISPLAY_NAMES = {
    "alibaba": "Alibaba",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "deepseek": "DeepSeek",
    "xai": "xAI",
    "mistral": "Mistral",
    "groq": "Groq",
    "fireworks": "Fireworks",
    "together": "Together",
    "openrouter": "OpenRouter",
}

PROVIDER_AUTH_TYPES = {
    "alibaba": "api_key",
    "openai": "api_key",
    "anthropic": "api_key",
    "google": "api_key",
    "deepseek": "api_key",
    "xai": "api_key",
    "mistral": "api_key",
    "groq": "api_key",
    "fireworks": "api_key",
    "together": "api_key",
    "openrouter": "api_key",
}

PROVIDER_ENV_VARS = {
    "alibaba": "DASHSCOPE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "together": "TOGETHER_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _read_config_yaml():
    """读取 config.yaml"""
    config_path = get_hermes_home() / "config.yaml"
    if not config_path.exists():
        print(f"[ERROR] 配置文件不存在: {config_path}")
        return None
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _now_ms():
    """当前时间戳（毫秒）"""
    return int(time.time() * 1000)


def _migrate_model_configs(db_mgr, config: dict, dry_run: bool) -> int:
    """
    迁移模型配置。

    从 config.yaml model 节点 → model_configs 表
    """
    model_config = config.get("model", {})
    if not isinstance(model_config, dict):
        return 0

    model_name = model_config.get("default", "")
    provider_key = model_config.get("provider", "")
    base_url = model_config.get("base_url", "")

    if not model_name:
        print("[SKIP] model_configs: model.default 未设置")
        return 0

    # 检查是否已存在
    existing = db_mgr.fetchone(
        "SELECT id FROM model_configs WHERE profile_name = %s AND model_name = %s AND provider_key = %s",
        "default", model_name, provider_key,
    )
    if existing:
        print(f"[SKIP] model_configs: {model_name} ({provider_key}) 已存在")
        return 0

    new_id = get_id_generator().next_id()
    now = _now_ms()
    if dry_run:
        print(f"[DRY-RUN] model_configs: 插入 {model_name} (provider={provider_key})")
        return 1

    db_mgr.execute(
        "INSERT INTO model_configs (id, profile_name, model_name, provider_key, max_tokens, "
        "temperature, top_p, is_default, enabled, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        new_id, "default", model_name, provider_key, 4096, 0.7, 1.0,
        1, 1, now, now,
    )
    print(f"[OK] model_configs: 插入 {model_name} (provider={provider_key})")
    return 1


def _migrate_provider_configs(db_mgr, config: dict, dry_run: bool) -> int:
    """
    迁移供应商配置。

    从 config.yaml providers 节点和 model.provider → provider_configs 表
    """
    count = 0
    now = _now_ms()
    model_provider = config.get("model", {}).get("provider", "") if isinstance(config.get("model"), dict) else ""

    # 如果 model.provider 是已知的内置供应商，确保它有一条 provider_config
    if model_provider and model_provider in PROVIDER_BASE_URLS:
        existing = db_mgr.fetchone(
            "SELECT id FROM provider_configs WHERE profile_name = %s AND provider_key = %s",
            "default", model_provider,
        )
        if not existing:
            base_url = PROVIDER_BASE_URLS.get(model_provider, "")
            display_name = PROVIDER_DISPLAY_NAMES.get(model_provider, model_provider)
            auth_type = PROVIDER_AUTH_TYPES.get(model_provider, "api_key")
            env_var = PROVIDER_ENV_VARS.get(model_provider, f"{model_provider.upper()}_API_KEY")

            if dry_run:
                print(f"[DRY-RUN] provider_configs: 插入 {model_provider}")
            else:
                new_id = get_id_generator().next_id()
                db_mgr.execute(
                    "INSERT INTO provider_configs (id, profile_name, provider_key, display_name, "
                    "api_mode, base_url, auth_type, env_var_name, enabled, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    new_id, "default", model_provider, display_name, "chat_completions",
                    base_url, auth_type, env_var, 1, now, now,
                )
                print(f"[OK] provider_configs: 插入 {model_provider}")
            count += 1

    # 处理 YAML 中的自定义 providers
    custom_providers = config.get("custom_providers", [])
    if isinstance(custom_providers, list):
        for cp in custom_providers:
            if not isinstance(cp, dict):
                continue
            name = cp.get("name", "")
            if not name:
                continue
            provider_key = f"custom:{name}"

            existing = db_mgr.fetchone(
                "SELECT id FROM provider_configs WHERE profile_name = %s AND provider_key = %s",
                "default", provider_key,
            )
            if existing:
                continue

            if dry_run:
                print(f"[DRY-RUN] provider_configs: 插入自定义供应商 {provider_key}")
            else:
                new_id = get_id_generator().next_id()
                db_mgr.execute(
                    "INSERT INTO provider_configs (id, profile_name, provider_key, display_name, "
                    "api_mode, base_url, auth_type, env_var_name, enabled, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    new_id, "default", provider_key, cp.get("name", provider_key),
                    cp.get("api_mode", "chat_completions"),
                    cp.get("base_url", ""),
                    cp.get("auth_type", "api_key"),
                    f"CUSTOM_{name.upper()}_API_KEY",
                    1, now, now,
                )
                print(f"[OK] provider_configs: 插入自定义供应商 {provider_key}")
            count += 1

    return count


def _migrate_toolset_configs(db_mgr, config: dict, dry_run: bool) -> int:
    """
    迁移工具集配置。

    从 config.yaml toolsets + platform_toolsets → toolset_configs 表
    """
    count = 0
    now = _now_ms()

    # CLI 工具集
    cli_toolsets = config.get("toolsets", [])
    if isinstance(cli_toolsets, list):
        for toolset_name in cli_toolsets:
            if not toolset_name:
                continue
            existing = db_mgr.fetchone(
                "SELECT id FROM toolset_configs WHERE profile_name = %s AND platform = %s AND toolset_name = %s",
                "default", "cli", toolset_name,
            )
            if existing:
                continue
            if dry_run:
                print(f"[DRY-RUN] toolset_configs: cli/{toolset_name}")
            else:
                new_id = get_id_generator().next_id()
                db_mgr.execute(
                    "INSERT INTO toolset_configs (id, profile_name, platform, toolset_name, enabled, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    new_id, "default", "cli", toolset_name, 1, now, now,
                )
                print(f"[OK] toolset_configs: cli/{toolset_name}")
            count += 1

    # 平台工具集
    platform_toolsets = config.get("platform_toolsets", {})
    if isinstance(platform_toolsets, dict):
        for platform, toolsets in platform_toolsets.items():
            if not isinstance(toolsets, list):
                continue
            for toolset_name in toolsets:
                if not toolset_name:
                    continue
                existing = db_mgr.fetchone(
                    "SELECT id FROM toolset_configs WHERE profile_name = %s AND platform = %s AND toolset_name = %s",
                    "default", platform, toolset_name,
                )
                if existing:
                    continue
                if dry_run:
                    print(f"[DRY-RUN] toolset_configs: {platform}/{toolset_name}")
                else:
                    new_id = get_id_generator().next_id()
                    db_mgr.execute(
                        "INSERT INTO toolset_configs (id, profile_name, platform, toolset_name, enabled, created_at, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        new_id, "default", platform, toolset_name, 1, now, now,
                    )
                    print(f"[OK] toolset_configs: {platform}/{toolset_name}")
                count += 1

    return count


def _migrate_platform_configs(db_mgr, config: dict, dry_run: bool) -> int:
    """
    迁移平台配置。

    从 telegram.* / discord.* / slack.* 等 → platform_configs 表
    """
    count = 0
    now = _now_ms()

    # 已知的平台名称
    platform_names = [
        "telegram", "discord", "slack", "whatsapp", "matrix",
        "mattermost", "signal", "irc", "qqbot", "yuanbao", "teams",
        "homeassistant",
    ]

    for platform in platform_names:
        platform_config = config.get(platform, None)
        if not isinstance(platform_config, dict):
            continue

        for config_key, config_value in platform_config.items():
            if config_key.startswith("_"):
                continue
            if config_value is None:
                continue
            if isinstance(config_value, (dict, list)):
                config_value = str(config_value)

            existing = db_mgr.fetchone(
                "SELECT id FROM platform_configs WHERE profile_name = %s AND platform = %s AND config_key = %s",
                "default", platform, config_key,
            )
            if existing:
                continue

            if dry_run:
                print(f"[DRY-RUN] platform_configs: {platform}.{config_key} = {config_value}")
            else:
                new_id = get_id_generator().next_id()
                db_mgr.execute(
                    "INSERT INTO platform_configs (id, profile_name, platform, config_key, config_value, "
                    "is_secret, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    new_id, "default", platform, config_key, str(config_value),
                    0, now, now,
                )
                print(f"[OK] platform_configs: {platform}.{config_key} = {config_value}")
            count += 1

    return count


def main():
    dry_run = "--dry-run" in sys.argv

    # 检测数据库模式
    if os.environ.get("HERMES_DB_TYPE", "sqlite").lower() not in ("mysql", "postgresql", "postgres", "pg"):
        print("=" * 60)
        print("错误: 未启用共享数据库模式")
        print("请先设置环境变量: HERMES_DB_TYPE=mysql")
        print("=" * 60)
        sys.exit(1)

    # 加载配置
    config = _read_config_yaml()
    if config is None:
        sys.exit(1)

    # 初始化数据库
    from db.connection import get_db_manager
    db_mgr = get_db_manager()
    db_mgr.initialize()

    print("=" * 60)
    print("配置数据迁移 (YAML → 共享数据库)")
    if dry_run:
        print(">>> DRY RUN 模式 — 不会实际写入 <<<")
    print("=" * 60)
    print()

    total = 0

    print("[1/4] 迁移模型配置...")
    total += _migrate_model_configs(db_mgr, config, dry_run)
    print()

    print("[2/4] 迁移供应商配置...")
    total += _migrate_provider_configs(db_mgr, config, dry_run)
    print()

    print("[3/4] 迁移工具集配置...")
    total += _migrate_toolset_configs(db_mgr, config, dry_run)
    print()

    print("[4/4] 迁移平台配置...")
    total += _migrate_platform_configs(db_mgr, config, dry_run)
    print()

    print("=" * 60)
    if dry_run:
        print(f">>> DRY RUN 完成: 共 {total} 条记录将被迁移 <<<")
    else:
        print(f"迁移完成: 共迁移 {total} 条记录")
    print("=" * 60)


if __name__ == "__main__":
    main()
