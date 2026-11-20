"""RPA共享字段数据集的业务不变量测试。

覆盖题目中的关键口径：
- 只交付可读字段与核对行号，受控原值留在原执行批次；
- 范围放宽生成新版本，已签收旧批次保持原快照，并能生成独立核对的新批次；
- 重采按样本UID匹配同一行，重复行不能借体重交原值，已签收批次不回改；
- 完整率只计授权字段并区分原值为空；返查逐票还原送检依据。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    c = TestClient(app)
    # 每个用例前把演示数据恢复到初始两批次状态，避免用例间互相污染
    c.post("/api/rpa_share/reset_demo")
    return c


def _records(client: TestClient, dataset_no: str) -> list[dict]:
    return client.get(
        "/api/rpa_share/records",
        params={"dataset_no": dataset_no, "size": 200},
    ).json()["items"]


def test_demo_seed_two_lists_under_two_scopes(client: TestClient) -> None:
    batches = client.get("/api/rpa_share").json()["items"]
    assert [(b["数据集编号"], b["status"], b["范围编号"]) for b in batches] == [
        ("RPS-0001", "已签收", "SCP-0001"),
        ("RPS-0002", "待签收", "SCP-0002"),
    ]
    assert len(_records(client, "RPS-0001")) == 12
    assert len(_records(client, "RPS-0002")) == 8
    scopes = client.get("/api/rpa_share/scopes").json()["items"]
    assert [s["版本号"] for s in scopes] == [1, 2]


def test_first_list_only_delivers_waybill_phone_restricted(client: TestClient) -> None:
    for record in _records(client, "RPS-0001"):
        assert record["运单号"]
        assert record["联系电话"] is None
        assert record["电话口径"] == "未授权"
        assert record["字段明细"]["联系电话"]["共享级别"] == "受限"


def test_second_list_delivers_masked_phone_and_marks_empty(client: TestClient) -> None:
    records = _records(client, "RPS-0002")
    masked = [r for r in records if r["电话口径"] == "脱敏可读"]
    empty = [r for r in records if r["电话口径"] == "原值为空"]
    assert len(masked) == 6
    assert len(empty) == 2
    assert {r["运单号"] for r in empty} == {"YD2026112017", "YD2026112019"}
    sample = next(r for r in records if r["运单号"] == "YD2026112013")
    assert sample["联系电话"] == "139****0013"
    # 核对行号始终可回溯到页面行与原执行批次
    assert sample["页面行号"] == 13
    assert sample["样本UID"] == "SMP-013"
    assert sample["执行批次"] == "EXEC-20261120-01"


def test_delivery_surface_never_contains_raw_values(client: TestClient) -> None:
    raw_phones = [f"139{seq:08d}" for seq in range(1, 21) if seq not in (17, 19)]
    surfaces = [
        client.get("/api/rpa_share").json(),
        client.get("/api/rpa_share/records", params={"size": 1000}).json(),
        client.get("/api/rpa_share/scopes").json(),
        client.get("/api/ingestion/share-completeness", params={"dataset_no": "RPS-0002"}).json(),
        client.post(
            "/api/rpa_share/recheck",
            json={"values": {"数据集编号": "RPS-0002", "票号": ["YD2026112013"]}},
        ).json(),
    ]
    import json

    blob = json.dumps(surfaces, ensure_ascii=False)
    assert all(raw not in blob for raw in raw_phones)
    # 原值只留在执行批次留档表
    exec_rows = client.get("/api/rpa_share/exec_samples").json()["items"]
    assert "13900000013" in {row["联系电话原值"] for row in exec_rows}


def test_completeness_counts_only_authorized_fields(client: TestClient) -> None:
    first = client.get(
        "/api/ingestion/share-completeness", params={"dataset_no": "RPS-0001"}
    ).json()
    phone_line = next(f for f in first["字段明细"] if f["字段"] == "联系电话")
    assert phone_line["是否计入"] is False
    assert phone_line["未授权数"] == 12
    assert phone_line["完整率"] is None
    assert first["综合完整率"] == 1.0
    assert first["授权字段总数"] == 12
    assert first["未授权字段总数"] == 12

    second = client.get(
        "/api/ingestion/share-completeness", params={"dataset_no": "RPS-0002"}
    ).json()
    phone_line = next(f for f in second["字段明细"] if f["字段"] == "联系电话")
    assert phone_line["是否计入"] is True
    assert phone_line["已填数"] == 6
    assert phone_line["原值为空数"] == 2  # 空值与未授权明确区分
    assert phone_line["完整率"] == 0.75
    assert second["综合完整率"] == 0.875


def test_ingestion_channel_missing_dataset_404(client: TestClient) -> None:
    resp = client.get(
        "/api/ingestion/share-completeness", params={"dataset_no": "RPS-9999"}
    )
    assert resp.status_code == 404


def test_recheck_replays_signed_list_basis_per_ticket(client: TestClient) -> None:
    result = client.post(
        "/api/rpa_share/recheck",
        json={"values": {
            "数据集编号": "RPS-0001",
            "票号": ["YD2026112001", "YD2026112017", "YD2026112019"],
        }},
    ).json()["entry"]
    assert result["清单状态"] == "已签收"
    assert result["签收时间"] == "2026-11-20 09:45:00"
    assert result["清单外票号"] == ["YD2026112017", "YD2026112019"]
    ticket = result["返查明细"][0]
    assert ticket["运单号"] == "YD2026112001"
    assert ticket["页面行号"] == 1
    assert ticket["逐字段依据"]["联系电话"]["口径"] == "未授权"
    assert ticket["逐字段依据"]["联系电话"]["当时交付值"] is None

    second = client.post(
        "/api/rpa_share/recheck",
        json={"values": {"数据集编号": "RPS-0002", "票号": ["YD2026112017"]}},
    ).json()["entry"]
    basis = second["返查明细"][0]["逐字段依据"]["联系电话"]
    assert basis["口径"] == "原值为空"
    assert basis["当时交付值"] == ""


def test_scope_widen_makes_new_version_but_keeps_old_snapshot(client: TestClient) -> None:
    resp = client.post(
        "/api/rpa_share/scopes/widen",
        json={"values": {"联系电话": "明文", "备注": "再次放宽"}},
    )
    assert resp.json()["ok"] is True
    scopes = client.get("/api/rpa_share/scopes").json()["items"]
    assert [s["版本号"] for s in scopes] == [1, 2, 3]
    assert scopes[1]["status"] == "已替代"
    old_batch = next(
        b for b in client.get("/api/rpa_share").json()["items"]
        if b["数据集编号"] == "RPS-0001"
    )
    # 已签收旧清单的快照仍是 v1 口径
    assert old_batch["范围快照"][1] == {"字段": "联系电话", "共享级别": "受限"}


def test_scope_tighten_and_noop_are_rejected(client: TestClient) -> None:
    tightened = client.post(
        "/api/rpa_share/scopes/widen", json={"values": {"联系电话": "受限"}}
    ).json()
    assert tightened["ok"] is False
    assert "收紧" in tightened["message"]
    noop = client.post(
        "/api/rpa_share/scopes/widen", json={"values": {"联系电话": "脱敏"}}
    ).json()
    assert noop["ok"] is False


def test_new_batch_under_widened_scope_is_separately_checkable(client: TestClient) -> None:
    client.post(
        "/api/rpa_share/scopes/widen", json={"values": {"联系电话": "明文"}}
    )
    created = client.post(
        "/api/rpa_share",
        json={"values": {"数据集名称": "扩权后重送12票", "扫描序号起": 1, "扫描序号止": 12}},
    ).json()["entry"]
    assert created["数据集编号"] == "RPS-0003"
    assert created["范围编号"] == "SCP-0003"
    records = _records(client, "RPS-0003")
    assert len(records) == 12
    assert records[0]["联系电话"] == "13900000001"  # 新口径明文，与旧清单互不影响
    # 旧清单仍是 12 票且电话未授权
    assert all(r["电话口径"] == "未授权" for r in _records(client, "RPS-0001"))


def test_recollect_by_uid_matches_same_row_without_using_duplicate(client: TestClient) -> None:
    # 重复行（与第15票同号）重采必须被拒绝
    dup = client.post(
        "/api/rpa_share/recollect",
        json={"values": {"样本UID": "SMP-021", "联系电话": "13900009999"}},
    ).json()
    assert dup["ok"] is False
    assert "重复行" in dup["message"]

    # 缺 UID 直接拒绝，脱敏后的可见键不能作为匹配入口
    no_uid = client.post(
        "/api/rpa_share/recollect",
        json={"values": {"运单号": "YD2026112015"}},
    ).json()
    assert no_uid["ok"] is False

    # 按 UID 重采第 17 票（补填电话）并改动运单号，仍匹配同一行
    ok = client.post(
        "/api/rpa_share/recollect",
        json={"values": {"样本UID": "SMP-017", "运单号": "YD2026112017R", "联系电话": "13900007717"}},
    ).json()
    assert ok["ok"] is True
    records = _records(client, "RPS-0002")
    matched = [r for r in records if r["样本UID"] == "SMP-017"]
    assert len(matched) == 1  # 没有因键值变化产生重复交付
    assert matched[0]["页面行号"] == 17
    assert matched[0]["运单号"] == "YD2026112017R"
    assert matched[0]["联系电话"] == "139****7717"  # 交付侧只拿到脱敏值


def test_signed_batch_is_not_mutated_by_recollect(client: TestClient) -> None:
    client.post(
        "/api/rpa_share/recollect",
        json={"values": {"样本UID": "SMP-005", "联系电话": "13900005555"}},
    )
    old_records = _records(client, "RPS-0001")
    assert len(old_records) == 12
    assert all(r["联系电话"] is None and r["电话口径"] == "未授权" for r in old_records)
    # 原值仅回写执行批次留档
    sample = next(
        row for row in client.get("/api/rpa_share/exec_samples").json()["items"]
        if row["样本UID"] == "SMP-005"
    )
    assert sample["联系电话原值"] == "13900005555"
    assert len(sample["重采历史"]) == 1


def test_sign_freezes_batch_and_blocks_double_sign(client: TestClient) -> None:
    batch = next(
        b for b in client.get("/api/rpa_share").json()["items"]
        if b["数据集编号"] == "RPS-0002"
    )
    first = client.post(
        f"/api/rpa_share/{batch['id']}/actions",
        json={"values": {"action": "签收清单"}},
    ).json()
    assert first["ok"] is True
    second = client.post(
        f"/api/rpa_share/{batch['id']}/actions",
        json={"values": {"action": "签收清单"}},
    ).json()
    assert second["ok"] is False
    # 签收后再重采，该批次也不再回改
    client.post(
        "/api/rpa_share/recollect",
        json={"values": {"样本UID": "SMP-013", "联系电话": "13900003313"}},
    )
    record = next(r for r in _records(client, "RPS-0002") if r["样本UID"] == "SMP-013")
    assert record["联系电话"] == "139****0013"
