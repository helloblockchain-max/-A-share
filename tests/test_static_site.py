from __future__ import annotations

from scripts.build_static_site import public_fallback_warning


def test_public_fallback_warning_hides_raw_network_error() -> None:
    warning = public_fallback_warning(
        RuntimeError(
            "东方财富全A快照第 1 页请求失败：HTTPSConnectionPool(host='push2.eastmoney.com', "
            "port=443): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=100&fields=f1,f2"
        )
    )

    assert "东方财富全A快照" in warning
    assert "HTTPSConnectionPool" not in warning
    assert "/api/qt/clist/get" not in warning
