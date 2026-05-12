"""
测试 config_db.py：从 MySQL 数据库加载配置覆盖。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def setup_db():
    """准备测试数据库和数据"""
    os.environ["HERMES_DB_TYPE"] = "mysql"
    os.environ["HERMES_DB_URL"] = "mysql://root:root@127.0.0.1:3306/hermes"

    import importlib
    import db.connection
    importlib.reload(db.connection)

    from db.connection import init_database
    from db.schema import init_schema

    db_mgr = init_database()
    init_schema(db_mgr)
    return db_mgr


def test_agent_settings(db_mgr):
    """测试 agent_settings 加载"""
    print("=" * 60)
    print("Test 1: agent_settings 加载")
    print("=" * 60)

    from hermes_cli.config_db import load_db_overrides
    import importlib
    import hermes_cli.config_db
    importlib.reload(hermes_cli.config_db)

    # 先删除默认值，再插入测试数据
    from db.id_generator import get_id_generator
    id_gen = get_id_generator()
    now = int(__import__("time").time() * 1000)

    db_mgr.execute(
        "DELETE FROM agent_settings WHERE profile_name = %s AND setting_key = %s",
        "default", "memory_enabled"
    )
    db_mgr.execute(
        "DELETE FROM agent_settings WHERE profile_name = %s AND setting_key = %s",
        "default", "max_iterations"
    )

    params1 = (id_gen.next_id(), "default", "memory_enabled", "true", now, now)
    db_mgr.execute(
        "INSERT INTO agent_settings (id, profile_name, setting_key, setting_value, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)", *params1
    )
    params2 = (id_gen.next_id(), "default", "max_iterations", "50", now, now)
    db_mgr.execute(
        "INSERT INTO agent_settings (id, profile_name, setting_key, setting_value, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)", *params2
    )

    overrides = load_db_overrides("default")
    assert "memory" in overrides, f"memory section missing: {overrides}"
    assert overrides["memory"]["memory_enabled"] is True
    print("  [PASS] memory_enabled = True")

    assert "agent" in overrides
    assert overrides["agent"]["max_turns"] == 50
    print("  [PASS] max_turns = 50")

    print("  Test 1: PASSED\n")


def test_model_configs(db_mgr):
    """测试 model_configs 加载"""
    print("=" * 60)
    print("Test 2: model_configs 加载")
    print("=" * 60)

    import importlib
    import hermes_cli.config_db
    importlib.reload(hermes_cli.config_db)
    from hermes_cli.config_db import load_db_overrides
    from db.id_generator import get_id_generator
    id_gen = get_id_generator()
    now = int(__import__("time").time() * 1000)

    # 插入默认模型
    params = (id_gen.next_id(), "default", "anthropic/claude-sonnet-4", "openrouter", 1, 1, now, now)
    db_mgr.execute(
        "INSERT IGNORE INTO model_configs (id, profile_name, model_name, provider_key, is_default, enabled, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", *params
    )

    overrides = load_db_overrides("default")
    assert overrides.get("model") == "anthropic/claude-sonnet-4", f"model mismatch: {overrides}"
    print("  [PASS] model = anthropic/claude-sonnet-4")

    print("  Test 2: PASSED\n")


def test_provider_configs(db_mgr):
    """测试 provider_configs 加载"""
    print("=" * 60)
    print("Test 3: provider_configs 加载")
    print("=" * 60)

    import importlib
    import hermes_cli.config_db
    importlib.reload(hermes_cli.config_db)
    from hermes_cli.config_db import load_db_overrides
    from db.id_generator import get_id_generator
    id_gen = get_id_generator()
    now = int(__import__("time").time() * 1000)

    params = (id_gen.next_id(), "default", "openrouter", "OpenRouter", "chat_completions",
              "https://openrouter.ai/api/v1", "api_key", "OPENROUTER_API_KEY", 1, now, now)
    db_mgr.execute(
        "INSERT IGNORE INTO provider_configs "
        "(id, profile_name, provider_key, display_name, api_mode, base_url, auth_type, env_var_name, enabled, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", *params
    )

    overrides = load_db_overrides("default")
    assert "providers" in overrides, f"providers section missing: {overrides}"
    providers = overrides["providers"]
    assert "openrouter" in providers, f"openrouter not found in providers: {providers}"

    p = providers["openrouter"]
    assert p["name"] == "OpenRouter"
    assert p["base_url"] == "https://openrouter.ai/api/v1"
    assert p["api_mode"] == "chat_completions"
    assert p["key_env"] == "OPENROUTER_API_KEY"
    print("  [PASS] provider 'openrouter' all fields correct")

    print("  Test 3: PASSED\n")


def test_toolset_configs(db_mgr):
    """测试 toolset_configs 加载"""
    print("=" * 60)
    print("Test 4: toolset_configs 加载")
    print("=" * 60)

    import importlib
    import hermes_cli.config_db
    importlib.reload(hermes_cli.config_db)
    from hermes_cli.config_db import load_db_overrides
    from db.id_generator import get_id_generator
    id_gen = get_id_generator()
    now = int(__import__("time").time() * 1000)

    p1 = (id_gen.next_id(), "default", "cli", "web", 1, now, now)
    db_mgr.execute(
        "INSERT IGNORE INTO toolset_configs "
        "(id, profile_name, platform, toolset_name, enabled, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)", *p1
    )
    p2 = (id_gen.next_id(), "default", "cli", "browser", 0, now, now)
    db_mgr.execute(
        "INSERT IGNORE INTO toolset_configs "
        "(id, profile_name, platform, toolset_name, enabled, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)", *p2
    )

    overrides = load_db_overrides("default")
    assert "toolsets" in overrides, f"toolsets missing: {overrides}"
    assert "web" in overrides["toolsets"]
    print("  [PASS] toolsets includes 'web'")

    assert "agent" in overrides
    assert "disabled_toolsets" in overrides["agent"]
    assert "browser" in overrides["agent"]["disabled_toolsets"]
    print("  [PASS] disabled_toolsets includes 'browser'")

    print("  Test 4: PASSED\n")


def test_skill_configs(db_mgr):
    """测试 skill_configs 加载"""
    print("=" * 60)
    print("Test 5: skill_configs 加载")
    print("=" * 60)

    import importlib
    import hermes_cli.config_db
    importlib.reload(hermes_cli.config_db)
    from hermes_cli.config_db import load_db_overrides
    from db.id_generator import get_id_generator
    id_gen = get_id_generator()
    now = int(__import__("time").time() * 1000)

    p1 = (id_gen.next_id(), "default", "software-development/debugging", "all", 1, 1, now, now)
    db_mgr.execute(
        "INSERT IGNORE INTO skill_configs "
        "(id, profile_name, skill_path, platform, enabled, pinned, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", *p1
    )
    p2 = (id_gen.next_id(), "default", "legacy/old-skill", "all", 0, 0, now, now)
    db_mgr.execute(
        "INSERT IGNORE INTO skill_configs "
        "(id, profile_name, skill_path, platform, enabled, pinned, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", *p2
    )

    overrides = load_db_overrides("default")
    assert "skills" in overrides, f"skills missing: {overrides}"

    skills = overrides["skills"]
    assert "pinned" in skills
    assert "software-development/debugging" in skills["pinned"]
    print("  [PASS] pinned skill loaded")

    assert "disabled" in skills
    assert "legacy/old-skill" in skills["disabled"]
    print("  [PASS] disabled skill loaded")

    print("  Test 5: PASSED\n")


def test_platform_configs(db_mgr):
    """测试 platform_configs 加载"""
    print("=" * 60)
    print("Test 6: platform_configs 加载")
    print("=" * 60)

    import importlib
    import hermes_cli.config_db
    importlib.reload(hermes_cli.config_db)
    from hermes_cli.config_db import load_db_overrides
    from db.id_generator import get_id_generator
    id_gen = get_id_generator()
    now = int(__import__("time").time() * 1000)

    p1 = (id_gen.next_id(), "default", "telegram", "reactions", "true", 0, now, now)
    db_mgr.execute(
        "INSERT IGNORE INTO platform_configs "
        "(id, profile_name, platform, config_key, config_value, is_secret, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", *p1
    )
    p2 = (id_gen.next_id(), "default", "discord", "require_mention", "false", 0, now, now)
    db_mgr.execute(
        "INSERT IGNORE INTO platform_configs "
        "(id, profile_name, platform, config_key, config_value, is_secret, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", *p2
    )

    overrides = load_db_overrides("default")
    assert "telegram" in overrides, f"telegram section missing: {overrides}"
    assert overrides["telegram"]["reactions"] is True
    print("  [PASS] telegram.reactions = True")

    assert "discord" in overrides
    assert overrides["discord"]["require_mention"] is False
    print("  [PASS] discord.require_mention = False")

    print("  Test 6: PASSED\n")


def test_clean_db():
    """清理测试数据"""
    import importlib
    import db.connection
    importlib.reload(db.connection)
    from db.connection import get_db_manager

    db_mgr = get_db_manager()
    db_mgr.initialize()

    tables = ["agent_settings", "model_configs", "provider_configs",
              "toolset_configs", "skill_configs", "platform_configs"]
    for table in tables:
        db_mgr.execute(f"DELETE FROM {table} WHERE profile_name = %s", "default")

    db_mgr.close()


if __name__ == "__main__":
    try:
        # 清理环境
        for key in ("HERMES_DB_TYPE", "HERMES_DB_URL"):
            os.environ.pop(key, None)

        # 清理旧数据
        os.environ["HERMES_DB_TYPE"] = "mysql"
        os.environ["HERMES_DB_URL"] = "mysql://root:root@127.0.0.1:3306/hermes"
        test_clean_db()

        db_mgr = setup_db()

        test_agent_settings(db_mgr)
        test_model_configs(db_mgr)
        test_provider_configs(db_mgr)
        test_toolset_configs(db_mgr)
        test_skill_configs(db_mgr)
        test_platform_configs(db_mgr)

        test_clean_db()

        print("=" * 60)
        print("ALL CONFIG DB TESTS PASSED")
        print("=" * 60)
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
