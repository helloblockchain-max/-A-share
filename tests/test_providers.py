from __future__ import annotations

from ashare_indicator_monitor.providers import PublicDataProvider


class _FakeResponse:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"data": {"diff": self._rows}}


class _FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict, timeout: int):
        self.calls.append((url, dict(params)))
        page = int(params["pn"])
        if page == 1:
            return _FakeResponse([_row(i) for i in range(100)])
        if page == 2:
            return _FakeResponse([_row(i) for i in range(20)])
        return _FakeResponse([])


def _row(i: int) -> dict:
    return {
        "f2": 10 + i,
        "f3": 1.2,
        "f5": 1000,
        "f6": 1_000_000,
        "f8": 2.5,
        "f12": f"60{i:04d}"[-6:],
        "f14": f"测试{i}",
        "f20": 10_000_000,
        "f21": 8_000_000,
        "f24": 3.0,
        "f25": 4.0,
    }


def test_fetch_a_share_snapshot_paginates_with_100_row_limit(tmp_path) -> None:
    provider = PublicDataProvider(cache_dir=tmp_path, ttl_seconds=0)
    fake = _FakeSession()
    provider.session = fake  # type: ignore[assignment]

    frame = provider.fetch_a_share_snapshot()

    assert frame.quality.row_count == 120
    assert len(frame.data) == 120
    assert fake.calls[0][0] == "https://push2.eastmoney.com/api/qt/clist/get"
    assert fake.calls[0][1]["pz"] == "100"
    assert fake.calls[1][1]["pn"] == "2"
