from knowserve_core.db import _connect_args


def test_arch_12_pooled_neon_host_disables_prepared_statement_cache() -> None:
    assert _connect_args("postgresql+asyncpg://u:p@ep-a-pooler.region.neon.tech/db") == {
        "statement_cache_size": 0
    }
    assert _connect_args("postgresql+asyncpg://u:p@ep-a.region.neon.tech/db") == {}
    assert _connect_args("postgresql+asyncpg://u:p@localhost:5433/db") == {}
