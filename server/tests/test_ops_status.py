import json
from datetime import timedelta
from decimal import Decimal

from modurouter import ops_status
from modurouter.billing import quota_day
from modurouter.config import Settings
from modurouter.db import utcnow
from modurouter.models import Job, QuotaBucket, SyncState


async def test_aggregate_status_reports_spending_without_global_cap_or_job_payload(database, monkeypatch):
    monkeypatch.setattr(ops_status, "Session", database)
    monkeypatch.setattr(ops_status, "get_settings", lambda: Settings(_env_file=None, openrouter_api_key="test-key"))
    async with database.begin() as db:
        (await db.get(SyncState, "openrouter")).last_success_at = utcnow()
        db.add(QuotaBucket(scope="platform", scope_id="global", quota_date=quota_day(),
                           request_count=3, spent_usd=Decimal("1.25"),
                           reserved_usd=Decimal("0.50"), limit_usd=None))
        db.add(Job(type="extract", payload={"private": "do-not-log"}, status="queued",
                   created_at=utcnow() - timedelta(seconds=12)))
        db.add(Job(type="delete_file", payload={}, status="failed"))
    result = await ops_status.snapshot()
    assert result["price"]["stale"] is False
    assert result["platform"]["limit_usd"] is None
    assert result["platform"]["remaining_usd"] is None
    assert Decimal(result["platform"]["spent_usd"]) == Decimal("1.25")
    assert Decimal(result["platform"]["reserved_usd"]) == Decimal("0.50")
    assert result["pending_attempts"]["count"] == 0
    assert result["jobs"]["queued"] == 1 and result["jobs"]["failed"] == 1
    assert result["jobs"]["oldest_queued_age_seconds"] >= 12
    assert "do-not-log" not in json.dumps(result)
