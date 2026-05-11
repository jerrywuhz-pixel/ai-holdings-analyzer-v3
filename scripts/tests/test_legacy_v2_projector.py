from scripts.legacy_v2_projector import generate_projection_sql


TENANT_ID = "11111111-1111-1111-1111-111111111111"


def test_legacy_projector_generates_additive_projection_sql():
    sql = generate_projection_sql()

    assert "legacy_v2_trade_events" in sql
    assert "FROM public.position_snapshots ps" in sql
    assert "INSERT INTO public.portfolio_positions" in sql
    assert "INSERT INTO public.equity_positions" in sql
    assert "INSERT INTO public.option_positions" in sql
    assert "regexp_match" in sql
    assert "source_lineage" in sql
    assert "DO UPDATE" in sql
    assert "DELETE" not in sql
    assert "DROP " not in sql


def test_legacy_projector_can_scope_projection_to_one_tenant():
    sql = generate_projection_sql(tenant_id=TENANT_ID)

    assert f"u.id = '{TENANT_ID}'::uuid" in sql
    assert f"ps.tenant_id = '{TENANT_ID}'::uuid" in sql
    assert f"ta.tenant_id = '{TENANT_ID}'::uuid" in sql


def test_legacy_projector_can_exclude_closed_positions():
    sql = generate_projection_sql(tenant_id=TENANT_ID, include_closed=False)

    assert "ps.total_quantity <> 0" in sql


def test_legacy_projector_default_keeps_closed_positions_for_history():
    sql = generate_projection_sql()

    assert "ps.total_quantity <> 0" not in sql
    assert "WHEN abs(total_quantity)::numeric = 0 THEN 'closed'" in sql
