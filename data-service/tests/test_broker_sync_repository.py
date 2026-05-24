from services.broker_sync import (
    PostgresBrokerSyncRepository,
    SupabaseBrokerSyncRepository,
    create_broker_sync_repository_from_env,
)


def test_factory_uses_postgres_repository_for_lightweight_server(monkeypatch):
    monkeypatch.setenv("BROKER_SYNC_REPOSITORY", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/ai_holdings")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    repository = create_broker_sync_repository_from_env()

    assert isinstance(repository, PostgresBrokerSyncRepository)


def test_factory_keeps_supabase_repository_when_configured(monkeypatch):
    class FakeSupabaseClient:
        pass

    monkeypatch.setenv("BROKER_SYNC_REPOSITORY", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.example")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setattr("services.broker_sync._create_supabase_client", lambda url, key: FakeSupabaseClient())

    repository = create_broker_sync_repository_from_env()

    assert isinstance(repository, SupabaseBrokerSyncRepository)
