"""Scheduling semantics of the pending-request queue.

`build_claim_query` is pure, so these tests need no database: they pin the
contract that a request with a future `scheduled_at` is invisible to the
scheduler until the instant passes.
"""

from datetime import datetime, timedelta, timezone

from app.db.documents import as_utc
from app.db.repositories import pending_requests_repo as repo

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


def test_undue_requests_excluded():
    query = repo.build_claim_query(NOW)
    ors = query["$or"]
    assert {"scheduled_at": None} in ors
    assert {"scheduled_at": {"$lte": NOW}} in ors
    assert query["status"] == repo.PENDING


def test_robot_type_filter_combined_under_and():
    query = repo.build_claim_query(NOW, robot_type="forklift_bot")
    # Two independent $or clauses must live under one $and (a dict cannot hold
    # two "$or" keys).
    assert set(query) == {"status", "$and"}
    clauses = query["$and"]
    assert {"$or": [{"robot_type": None}, {"robot_type": "forklift_bot"}]} in clauses
    due_clause = [c for c in clauses if "scheduled_at" in str(c)]
    assert len(due_clause) == 1


def test_no_robot_type_keeps_flat_query():
    query = repo.build_claim_query(NOW)
    assert "$and" not in query
    assert "scheduled_at" in str(query["$or"])


def test_as_utc_normalises_naive_and_offsets():
    naive = datetime(2026, 8, 23, 12, 0, 0)
    assert as_utc(native_tz := naive.replace(tzinfo=timezone.utc)) == native_tz

    offset = datetime(2026, 8, 23, 15, 30, 0, tzinfo=timezone(timedelta(hours=3)))
    assert as_utc(offset) == datetime(2026, 8, 23, 12, 30, 0, tzinfo=timezone.utc)

    assert as_utc(None) is None
