import json

from scripts.routing_to_channel_bindings import (
    channel_to_enum,
    find_routing_entries,
    generate_sql,
    load_entries,
    status_to_enum,
)


TENANT_ID = "22222222-2222-2222-2222-222222222222"


def test_find_routing_entries_supports_nested_payloads():
    payload = {
        "version": 1,
        "routes": [
            {
                "channel": "openclaw-weixin",
                "tenantId": TENANT_ID,
                "accountId": "wx-bot-main",
            }
        ],
    }

    entries = find_routing_entries(payload)

    assert len(entries) == 1
    assert entries[0]["tenantId"] == TENANT_ID
    assert entries[0]["accountId"] == "wx-bot-main"


def test_find_routing_entries_supports_snake_case_payloads():
    payload = {
        "bindings": [
            {
                "channel": "openclaw_wechat",
                "tenant_id": TENANT_ID,
                "openclaw_account_id": "wx-bot-snake",
            }
        ],
    }

    entries = find_routing_entries(payload)

    assert len(entries) == 1
    assert entries[0]["tenant_id"] == TENANT_ID
    assert entries[0]["openclaw_account_id"] == "wx-bot-snake"


def test_load_entries_normalizes_current_routing_json_fields(tmp_path):
    routing = tmp_path / "routing.json"
    routing.write_text(
        json.dumps(
            [
                {
                    "channel": "openclaw-weixin",
                    "tenantId": TENANT_ID,
                    "accountId": "wx-bot-main",
                    "accountLabel": "主账号",
                    "humanName": "Jerry",
                    "sessionSpace": "jerry-main",
                    "memoryRoot": "memory/jerry",
                    "sessionRoot": "sessions/jerry",
                    "identityRoot": "identity/jerry",
                    "dataRoot": "data/jerry",
                    "status": "active",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    entries = load_entries(routing)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.tenant_id == TENANT_ID
    assert entry.openclaw_account_id == "wx-bot-main"
    assert entry.account_label == "主账号"
    assert entry.human_name == "Jerry"
    assert entry.session_space == "jerry-main"
    assert entry.memory_root == "memory/jerry"
    assert entry.session_root == "sessions/jerry"
    assert entry.identity_root == "identity/jerry"
    assert entry.data_root == "data/jerry"


def test_generate_sql_maps_routing_json_to_channel_bindings(tmp_path):
    routing = tmp_path / "routing.json"
    routing.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "channel": "openclaw-weixin",
                        "tenantId": TENANT_ID,
                        "accountId": "wx-bot-main",
                        "accountLabel": "主账号",
                        "humanName": "Jerry",
                        "sessionSpace": "jerry-main",
                        "memoryRoot": "memory/jerry",
                        "sessionRoot": "sessions/jerry",
                        "identityRoot": "identity/jerry",
                        "dataRoot": "data/jerry",
                        "status": "active",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    sql = generate_sql(load_entries(routing))

    assert "INSERT INTO public.channel_bindings" in sql
    assert "'openclaw_wechat'::public.channel_type" in sql
    assert f"'{TENANT_ID}'::uuid" in sql
    assert "'wx-bot-main'" in sql
    assert "'jerry-main'" in sql
    assert "'memory/jerry'" in sql
    assert "'routing.json'" in sql
    assert "ON CONFLICT (tenant_id, channel, openclaw_account_id) DO UPDATE" in sql
    assert "DELETE" not in sql
    assert "DROP " not in sql


def test_channel_and_status_mappings_match_v3_enums():
    assert channel_to_enum("openclaw-weixin") == "openclaw_wechat"
    assert channel_to_enum("wechat_claw") == "openclaw_wechat"
    assert channel_to_enum("webapp") == "webapp_inbox"
    assert status_to_enum("active") == "active"
    assert status_to_enum("disabled") == "paused"
    assert status_to_enum("deleted") == "revoked"
    assert status_to_enum("unknown") == "pending"
