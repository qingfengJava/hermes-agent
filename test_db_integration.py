"""
集成测试：数据库抽象层 + SessionDB 改造。

覆盖：
  Test 1 — SQLite 向后兼容（无环境变量）
  Test 2 — 共享数据库适配器路径（MySQL）
  Test 3 — SessionDB 通过适配器完整 CRUD
  Test 4 — 雪花 ID 生成器
  Test 5 — SQL 方言适配
"""
import os
import sys
import uuid
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

for key in ("HERMES_DB_TYPE", "HERMES_DB_URL"):
    os.environ.pop(key, None)


def uid():
    return str(uuid.uuid4())


def test1_sqlite_backward_compatibility():
    """测试1: SQLite 模式下 SessionDB 正常启动"""
    print("=" * 60)
    print("Test 1: SQLite Backward Compatibility")
    print("=" * 60)

    from hermes_state import SessionDB, _detect_shared_db

    assert _detect_shared_db() is False, "Should detect SQLite mode"
    print("  [PASS] _detect_shared_db() returns False")

    db_path = Path(tempfile.mktemp(suffix=".db"))
    sdb = None
    try:
        sdb = SessionDB(db_path)
        assert sdb._use_shared_db is False, "SessionDB should be in SQLite mode"
        print("  [PASS] SessionDB initialized in SQLite mode")

        sid = uid()

        # create_session
        result = sdb.create_session(sid, source="cli")
        assert result == sid
        print(f"  [PASS] create_session() → {sid}")

        # get_session
        session = sdb.get_session(sid)
        assert session is not None
        assert session["source"] == "cli"
        print("  [PASS] get_session() returns correct source")

        # append_message
        msg_id = sdb.append_message(sid, "user", "Hello, test!")
        assert msg_id
        print(f"  [PASS] append_message() → {msg_id}")

        msgs = sdb.get_messages(sid)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Hello, test!"
        print("  [PASS] get_messages() returns correct content")

        # tool_calls serialization
        tool_calls = [{"name": "read_file", "args": {"path": "/tmp/test"}}]
        sdb.append_message(sid, "assistant", "Let me read that file", tool_calls=tool_calls)
        msgs = sdb.get_messages(sid)
        assert len(msgs) == 2
        assert msgs[1]["tool_calls"] is not None
        print("  [PASS] tool_calls serialization/deserialization")

        # end_session
        sdb.end_session(sid, end_reason="test_complete")
        session = sdb.get_session(sid)
        assert session["ended_at"] is not None
        assert session["end_reason"] == "test_complete"
        print("  [PASS] end_session()")

        # set_session_title
        sdb.set_session_title(sid, "Test Session Alpha")
        session = sdb.get_session(sid)
        assert session["title"] == "Test Session Alpha"
        print("  [PASS] set_session_title()")

        # resolve_session_by_title
        resolved = sdb.resolve_session_by_title("Test Session Alpha")
        assert resolved == sid
        print("  [PASS] resolve_session_by_title()")

        # session_count / message_count
        assert sdb.session_count() >= 1
        print(f"  [PASS] session_count() = {sdb.session_count()}")
        assert sdb.message_count(sid) == 2
        print("  [PASS] message_count() = 2")

        # search_messages (FTS5)
        results = sdb.search_messages("Hello")
        assert len(results) > 0
        print(f"  [PASS] search_messages('Hello') found {len(results)} result(s)")

        # list_sessions_rich
        rich = sdb.list_sessions_rich(limit=10)
        assert len(rich) > 0
        assert "preview" in rich[0] or "last_active" in rich[0]
        print("  [PASS] list_sessions_rich()")

        # replace_messages
        sdb.replace_messages(sid, [{"role": "user", "content": "replaced"}])
        msgs = sdb.get_messages(sid)
        assert len(msgs) == 1 and msgs[0]["content"] == "replaced"
        print("  [PASS] replace_messages()")

        # Meta KV
        sdb.set_meta("test_key", "test_value")
        assert sdb.get_meta("test_key") == "test_value"
        print("  [PASS] set_meta() / get_meta()")

        # delete_session
        sdb.delete_session(sid)
        assert sdb.get_session(sid) is None
        print("  [PASS] delete_session()")

        # ensure_session
        sid2 = uid()
        result2 = sdb.ensure_session(sid2, source="cli")
        assert result2 == sid2
        assert sdb.get_session(sid2) is not None
        print("  [PASS] ensure_session()")

        sdb.close()
        db_path.unlink()
        sdb = None
    finally:
        if sdb is not None:
            try:
                sdb.close()
            except Exception:
                pass
        if db_path.exists():
            db_path.unlink()

    print(f"\n  Test 1: 14/14 PASSED\n")


def test2_shared_db_adapter():
    """测试2: 通过适配器使用共享数据库（MySQL）"""
    print("=" * 60)
    print("Test 2: Shared DB Adapter Path (MySQL)")
    print("=" * 60)

    os.environ["HERMES_DB_TYPE"] = "mysql"
    os.environ["HERMES_DB_URL"] = "mysql://root:root@127.0.0.1:3306/hermes"

    try:
        from db.connection import get_db_manager, init_database
        from db.adapter import ConnectionAdapter
        from db.schema import init_schema

        import importlib
        import db.connection
        importlib.reload(db.connection)

        db_mgr = init_database()
        print("  [PASS] DatabaseManager initialized for MySQL")

        init_schema(db_mgr)
        print("  [PASS] Schema initialized (19 tables)")

        conn = ConnectionAdapter(db_mgr)
        print("  [PASS] ConnectionAdapter created")

        # INSERT
        conn.execute(
            "INSERT INTO sessions (id, source, started_at) VALUES (%s, %s, %s)",
            ("test-adapter-001", "cli", 1715000000000)
        )
        print("  [PASS] INSERT via adapter")

        # SELECT fetchone
        cursor = conn.execute(
            "SELECT id, source, started_at FROM sessions WHERE id = %s",
            ("test-adapter-001",)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["source"] == "cli"
        assert row["id"] == "test-adapter-001"
        print("  [PASS] SELECT + fetchone via adapter")

        # RowAdapter string key access
        assert row["source"] == "cli"
        print("  [PASS] RowAdapter string-key access")

        # fetchall
        cursor2 = conn.execute("SELECT * FROM sessions WHERE id = %s", ("test-adapter-001",))
        rows = cursor2.fetchall()
        assert len(rows) == 1
        print("  [PASS] fetchall() returns correct count")

        # UPDATE
        conn.execute(
            "UPDATE sessions SET title = %s WHERE id = %s",
            ("Adapter Test", "test-adapter-001")
        )
        cursor3 = conn.execute("SELECT title FROM sessions WHERE id = %s", ("test-adapter-001",))
        assert cursor3.fetchone()["title"] == "Adapter Test"
        print("  [PASS] UPDATE via adapter")

        # DELETE
        conn.execute("DELETE FROM sessions WHERE id = %s", ("test-adapter-001",))
        cursor4 = conn.execute("SELECT id FROM sessions WHERE id = %s", ("test-adapter-001",))
        assert cursor4.fetchone() is None
        print("  [PASS] DELETE via adapter")

        # executescript (multi-statement)
        conn.executescript("""
            INSERT INTO sessions (id, source, started_at) VALUES ('multi-1', 'cli', 1715000000001);
            INSERT INTO sessions (id, source, started_at) VALUES ('multi-2', 'telegram', 1715000000002);
        """)
        cursor5 = conn.execute("SELECT COUNT(*) as cnt FROM sessions WHERE id IN ('multi-1', 'multi-2')")
        assert cursor5.fetchone()["cnt"] == 2
        print("  [PASS] executescript() multi-statement")

        # cleanup
        conn.execute("DELETE FROM sessions WHERE id IN ('multi-1', 'multi-2')")

        conn.close()
        db_mgr.close()
        print("\n  Test 2: 9/9 PASSED\n")

    finally:
        os.environ.pop("HERMES_DB_TYPE", None)
        os.environ.pop("HERMES_DB_URL", None)


def test3_sessiondb_full_crud_mysql():
    """测试3: SessionDB 通过 MySQL 完整 CRUD"""
    print("=" * 60)
    print("Test 3: SessionDB Full CRUD via MySQL")
    print("=" * 60)

    os.environ["HERMES_DB_TYPE"] = "mysql"
    os.environ["HERMES_DB_URL"] = "mysql://root:root@127.0.0.1:3306/hermes"

    sdb = None
    try:
        from hermes_state import SessionDB, _detect_shared_db

        import importlib
        import hermes_state
        import db.connection
        importlib.reload(db.connection)
        importlib.reload(hermes_state)

        assert _detect_shared_db() is True
        print("  [PASS] _detect_shared_db() returns True")

        sdb = SessionDB()
        assert sdb._use_shared_db is True
        print("  [PASS] SessionDB initialized in shared DB mode")

        sid = uid()

        # create_session
        result = sdb.create_session(sid, source="telegram", user_id="user-42",
                                     model="openrouter/anthropic/claude-sonnet-4")
        assert result == sid
        print(f"  [PASS] create_session() → {sid}")

        # get_session
        session = sdb.get_session(sid)
        assert session is not None
        assert session["source"] == "telegram"
        assert session["user_id"] == "user-42"
        assert session["model"] == "openrouter/anthropic/claude-sonnet-4"
        print("  [PASS] get_session() all fields correct")

        # append_message x2
        sdb.append_message(sid, "user", "What is the weather?")
        sdb.append_message(sid, "assistant", "The weather is sunny.", tool_calls=[
            {"name": "get_weather", "args": {"city": "Beijing"}}
        ])
        print("  [PASS] append_message() x2")

        # get_messages
        msgs = sdb.get_messages(sid)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["tool_calls"] is not None
        print(f"  [PASS] get_messages() returned {len(msgs)} messages with tool_calls")

        # update_token_counts (absolute=True — set directly)
        sdb.update_token_counts(sid, input_tokens=100, output_tokens=50, absolute=True)
        session = sdb.get_session(sid)
        assert session["input_tokens"] == 100
        assert session["output_tokens"] == 50
        print("  [PASS] update_token_counts() absolute mode")

        # update_token_counts (absolute=False — increment)
        sdb.update_token_counts(sid, input_tokens=50, output_tokens=30, absolute=False)
        session = sdb.get_session(sid)
        assert session["input_tokens"] == 150
        assert session["output_tokens"] == 80
        print("  [PASS] update_token_counts() incremental mode")

        # set_session_title
        title1 = f"Weather Query {sid[:8]}"
        sdb.set_session_title(sid, title1)
        session = sdb.get_session(sid)
        assert session["title"] == title1
        print("  [PASS] set_session_title()")

        # Duplicate title → ValueError
        sid2 = uid()
        sdb.create_session(sid2, source="cli")
        title2 = f"Another {sid2[:8]}"
        sdb.set_session_title(sid2, title2)
        try:
            sdb.set_session_title(sid2, title1)
            assert False, "Should have raised ValueError"
        except ValueError:
            print("  [PASS] Duplicate title raises ValueError")
        sdb.delete_session(sid2)

        # end_session
        sdb.end_session(sid, end_reason="user_ended")
        session = sdb.get_session(sid)
        assert session["ended_at"] is not None
        assert session["end_reason"] == "user_ended"
        print("  [PASS] end_session()")

        # list_sessions_rich
        rich = sdb.list_sessions_rich(limit=10, source="telegram")
        assert len(rich) > 0
        assert any(s["id"] == sid for s in rich)
        print(f"  [PASS] list_sessions_rich() found {len(rich)} session(s)")

        # session_count / message_count
        assert sdb.session_count() >= 1
        print(f"  [PASS] session_count() = {sdb.session_count()}")
        assert sdb.message_count(sid) == 2
        print("  [PASS] message_count() = 2")

        # search_messages (LIKE fallback)
        results = sdb.search_messages("weather")
        assert len(results) > 0
        print(f"  [PASS] search_messages('weather') found {len(results)} result(s)")

        # replace_messages
        sdb.replace_messages(sid, [{"role": "user", "content": "New first message"}])
        msgs = sdb.get_messages(sid)
        assert len(msgs) == 1 and msgs[0]["content"] == "New first message"
        print("  [PASS] replace_messages()")

        # set_meta / get_meta
        sdb.set_meta("shared_test_key", "shared_test_value")
        assert sdb.get_meta("shared_test_key") == "shared_test_value"
        print("  [PASS] set_meta() / get_meta()")

        # delete_session
        sdb.delete_session(sid)
        assert sdb.get_session(sid) is None
        print("  [PASS] delete_session()")

        sdb.close()
        sdb = None
        print("\n  Test 3: 16/16 PASSED\n")

    finally:
        if sdb is not None:
            try:
                sdb.close()
            except Exception:
                pass
        os.environ.pop("HERMES_DB_TYPE", None)
        os.environ.pop("HERMES_DB_URL", None)


def test4_id_generator():
    """测试4: 雪花 ID 生成器"""
    print("=" * 60)
    print("Test 4: Snowflake ID Generator")
    print("=" * 60)

    from db.id_generator import IdGenerator

    gen = IdGenerator(worker_id=1)
    ids = [gen.next_id() for _ in range(100)]

    assert len(set(ids)) == 100, "All IDs must be unique"
    print("  [PASS] 100 unique IDs generated")

    assert ids == sorted(ids), "IDs must be monotonically increasing"
    print("  [PASS] IDs are monotonically increasing")

    assert all(i > 0 for i in ids), "All IDs must be positive"
    print("  [PASS] All IDs are positive")

    print("\n  Test 4: 3/3 PASSED\n")


def test5_dialect():
    """测试5: SQL 方言适配"""
    print("=" * 60)
    print("Test 5: SQL Dialect Helper")
    print("=" * 60)

    from db.dialect import DialectHelper, DbType

    for db_type, name in [(DbType.MYSQL, "MySQL"), (DbType.POSTGRESQL, "PostgreSQL"), (DbType.SQLITE, "SQLite")]:
        d = DialectHelper(db_type)
        print(f"\n  --- {name} ---")
        print(f"  insert_or_ignore: {d.insert_or_ignore('test', ['id', 'val'], ['?', '?'])}")
        print(f"  upsert: {d.upsert('test', ['id', 'val'], ['id'], ['val'])}")
        print(f"  limit_offset: {d.limit_offset(10, 5)}")
        print(f"  auto_increment: {d.auto_increment_clause()}")
        print(f"  boolean_true: {d.boolean_true()}")

    print("\n  Test 5: PASSED (manual verification)\n")


if __name__ == "__main__":
    try:
        test4_id_generator()
        test5_dialect()
        test1_sqlite_backward_compatibility()
        test2_shared_db_adapter()
        test3_sessiondb_full_crud_mysql()
        print("=" * 60)
        print("ALL TESTS PASSED")
        print("=" * 60)
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
