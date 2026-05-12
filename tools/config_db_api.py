"""
配置数据库 JSON-API —— 供 Web UI 通过 child_process 调用。

读取 stdin 的 JSON 请求，执行操作，输出 JSON 响应到 stdout。
所有状态通过 HTTP 风格的状态码和消息返回。

请求格式:
  {"action": "list", "table": "agent_settings", "profile": "default"}
  {"action": "create", "table": "model_configs", "data": {...}, "profile": "default"}
  {"action": "update", "table": "agent_settings", "id": 123, "data": {...}}
  {"action": "delete", "table": "model_configs", "id": 123}

支持的表:
  agent_settings, model_configs, provider_configs, toolset_configs,
  skill_configs, platform_configs

作者: 清风
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# 确保能导入 hermes-agent 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def init_db():
    """初始化数据库连接"""
    from db.connection import get_db_manager
    from db.schema import init_schema

    db_mgr = get_db_manager()
    db_mgr.initialize()
    init_schema(db_mgr)
    return db_mgr


# ── 表结构定义 ──────────────────────────────────────────────────────────

TABLE_SCHEMAS = {
    "agent_settings": {
        "columns": ["id", "profile_name", "setting_key", "setting_value",
                    "created_at", "updated_at"],
        "pk": "id",
        "readonly_cols": ["id", "created_at"],
    },
    "model_configs": {
        "columns": ["id", "profile_name", "model_name", "provider_key",
                    "max_tokens", "temperature", "top_p",
                    "is_default", "enabled", "created_at", "updated_at"],
        "pk": "id",
        "readonly_cols": ["id", "created_at"],
    },
    "provider_configs": {
        "columns": ["id", "profile_name", "provider_key", "display_name",
                    "api_mode", "base_url", "auth_type", "env_var_name",
                    "extra_body", "extra_headers", "enabled", "metadata",
                    "created_at", "updated_at"],
        "pk": "id",
        "readonly_cols": ["id", "created_at"],
    },
    "toolset_configs": {
        "columns": ["id", "profile_name", "platform", "toolset_name",
                    "enabled", "created_at", "updated_at"],
        "pk": "id",
        "readonly_cols": ["id", "created_at"],
    },
    "skill_configs": {
        "columns": ["id", "profile_name", "skill_path", "platform",
                    "enabled", "pinned", "created_at", "updated_at"],
        "pk": "id",
        "readonly_cols": ["id", "created_at"],
    },
    "platform_configs": {
        "columns": ["id", "profile_name", "platform", "config_key",
                    "config_value", "is_secret", "created_at", "updated_at"],
        "pk": "id",
        "readonly_cols": ["id", "created_at"],
    },
}


# ── 操作处理 ────────────────────────────────────────────────────────────

def handle_list(db_mgr, table: str, profile: str) -> Dict[str, Any]:
    """列出指定 profile 的所有记录"""
    if table not in TABLE_SCHEMAS:
        return {"success": False, "error": f"未知表: {table}"}

    schema = TABLE_SCHEMAS[table]
    cols = ", ".join(schema["columns"])

    if "profile_name" in schema["columns"]:
        rows = db_mgr.fetchall(
            f"SELECT {cols} FROM {table} WHERE profile_name = ? ORDER BY id",
            profile,
        )
    else:
        rows = db_mgr.fetchall(
            f"SELECT {cols} FROM {table} ORDER BY id"
        )

    # 转换非 JSON 可序列化的类型
    result = []
    for row in rows:
        item = {}
        for k, v in row.items():
            item[k] = _serialize_value(v)
        result.append(item)

    return {"success": True, "data": result}


def handle_create(db_mgr, table: str, profile: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """创建一条记录"""
    if table not in TABLE_SCHEMAS:
        return {"success": False, "error": f"未知表: {table}"}

    schema = TABLE_SCHEMAS[table]
    from db.id_generator import get_id_generator
    import time as _time

    id_gen = get_id_generator()
    new_id = id_gen.next_id()
    now = int(_time.time() * 1000)

    # 构建 INSERT 数据
    insert_data = {"id": new_id, "created_at": now, "updated_at": now}

    # 添加 profile_name（如果表有此列）
    if "profile_name" in schema["columns"]:
        insert_data["profile_name"] = profile

    # 合并用户提供的数据
    for k, v in data.items():
        if k in schema["readonly_cols"]:
            continue  # 跳过只读列
        if k in schema["columns"]:
            insert_data[k] = _deserialize_value(v, k)

    # 构建 SQL
    cols = []
    placeholders = []
    values = []
    for col in schema["columns"]:
        if col in insert_data:
            cols.append(col)
            placeholders.append("?")
            values.append(insert_data[col])

    cols_str = ", ".join(cols)
    ph_str = ", ".join(placeholders)
    sql = f"INSERT OR IGNORE INTO {table} ({cols_str}) VALUES ({ph_str})"

    try:
        db_mgr.execute(sql, *values)
        # 雪花 ID 超过 JS 安全整数，返回字符串
        return {"success": True, "id": str(new_id)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_update(db_mgr, table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """更新一条记录"""
    if table not in TABLE_SCHEMAS:
        return {"success": False, "error": f"未知表: {table}"}

    schema = TABLE_SCHEMAS[table]
    pk = schema["pk"]

    record_id = data.pop(pk, None)
    if record_id is None:
        return {"success": False, "error": f"缺少主键: {pk}"}
    # 支持字符串 ID（从 JS 传来避免精度丢失）
    if isinstance(record_id, str):
        record_id = int(record_id)

    import time as _time
    now = int(_time.time() * 1000)

    # 构建 SET 子句
    set_parts = []
    values = []
    for k, v in data.items():
        if k in schema["readonly_cols"]:
            continue
        if k in schema["columns"]:
            set_parts.append(f"{k} = ?")
            values.append(_deserialize_value(v, k))

    if not set_parts:
        return {"success": False, "error": "没有可更新的列"}

    set_parts.append("updated_at = ?")
    values.append(now)
    values.append(record_id)

    sql = f"UPDATE {table} SET {', '.join(set_parts)} WHERE {pk} = ?"

    try:
        affected = db_mgr.execute(sql, *values)
        return {"success": True, "affected": affected}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_delete(db_mgr, table: str, record_id) -> Dict[str, Any]:
    """删除一条记录"""
    if table not in TABLE_SCHEMAS:
        return {"success": False, "error": f"未知表: {table}"}

    schema = TABLE_SCHEMAS[table]
    pk = schema["pk"]
    # 支持字符串 ID（从 JS 传来避免精度丢失）
    if isinstance(record_id, str):
        record_id = int(record_id)

    try:
        affected = db_mgr.execute(f"DELETE FROM {table} WHERE {pk} = ?", record_id)
        return {"success": True, "affected": affected}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── 序列化辅助 ──────────────────────────────────────────────────────────

def _serialize_value(v: Any) -> Any:
    """将数据库值转换为 JSON 兼容格式"""
    if v is None:
        return None
    # 大整数转为字符串，避免 JavaScript 精度丢失
    # JavaScript Number.MAX_SAFE_INTEGER = 9007199254740991 (16 位)
    # 雪花算法 ID 是 18 位，必须用字符串传递
    if isinstance(v, int):
        if v > 9007199254740991 or v < -9007199254740991:
            return str(v)
        return v
    if isinstance(v, float):
        return v
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        if v.strip().startswith(("{", "[")):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                pass
        return v
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


def _deserialize_value(v: Any, col: str) -> Any:
    """将传入的 JSON 值转换为数据库格式"""
    if v is None:
        return None
    # JSON 列序列化为字符串
    if col in ("extra_body", "extra_headers", "metadata", "model_config"):
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return v
    # enabled/pinned/is_default 等布尔列
    if col in ("enabled", "pinned", "is_default", "is_secret"):
        if isinstance(v, bool):
            return 1 if v else 0
        if isinstance(v, str):
            return 1 if v.lower() in ("true", "1", "yes") else 0
        return int(v)
    return v


# ── 主入口 ──────────────────────────────────────────────────────────────

def main():
    try:
        raw = sys.stdin.read()
        request = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"success": False, "error": f"JSON 解析错误: {e}"}, sys.stdout)
        sys.exit(1)
    except EOFError:
        json.dump({"success": False, "error": "无输入"}, sys.stdout)
        sys.exit(1)

    action = request.get("action", "")
    table = request.get("table", "")
    profile = request.get("profile", "default")

    if not action or not table:
        json.dump({"success": False, "error": "缺少 action 或 table 参数"}, sys.stdout)
        sys.exit(1)

    # 初始化数据库
    try:
        db_mgr = init_db()
    except Exception as e:
        json.dump({"success": False, "error": f"数据库初始化失败: {e}"}, sys.stdout)
        sys.exit(1)

    # 路由到对应操作
    handlers = {
        "list": lambda: handle_list(db_mgr, table, profile),
        "create": lambda: handle_create(db_mgr, table, profile, request.get("data", {})),
        "update": lambda: handle_update(db_mgr, table, request.get("data", {})),
        "delete": lambda: handle_delete(db_mgr, table, request.get("id")),
    }

    handler = handlers.get(action)
    if not handler:
        json.dump({"success": False, "error": f"未知操作: {action}"}, sys.stdout)
        sys.exit(1)

    try:
        result = handler()
    except Exception as e:
        import traceback
        result = {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }

    json.dump(result, sys.stdout, ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()
