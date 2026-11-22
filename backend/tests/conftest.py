"""Test không gọi mạng: các hàm tải từ VNDirect (khối ngoại, BCTC, P/E) bị thay bằng bản báo lỗi mạng.
Test nào cần dữ liệu thì tự truyền fetcher giả."""
import pytest

from app import api
from app.core import fundamentals, foreign


def _offline(*a, **k):
    raise OSError("test: không gọi mạng")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    real_get_foreign, real_sync = foreign.get_foreign, fundamentals.sync
    monkeypatch.setattr(api, "get_foreign", lambda conn, code, end=None, n=foreign.MAX_SESSIONS:
                        real_get_foreign(conn, code, end, n, fetcher=_offline))
    monkeypatch.setattr(fundamentals, "sync", lambda conn, syms, workers=6, force=False, fetcher=None:
                        real_sync(conn, syms, workers, force, fetcher or _offline))
    monkeypatch.setattr(fundamentals, "fetch_pe", _offline)
    monkeypatch.setattr(fundamentals, "fetch", _offline)
