"""RPA共享字段数据集的演示数据与重建逻辑。

设计口径（对应业务约束）：
- 执行批次表 ``rpa_share_exec_sample`` 留存 RPA 采到的页面样本原值，受控字段原值只进这里；
- 共享范围表 ``rpa_share_scope`` 按版本登记每个字段的共享级别（明文/脱敏/受限），范围只许放宽；
- 共享批次表 ``rpa_share`` 是交付给质检组的数据集，生成时冻结当时的范围快照；
- 交付记录表 ``rpa_share_record`` 只保存可读字段（脱敏值）与核对行号，永不保存原值。

场景：同一批 20 票出库运单，采到一半承运方扩大授权——
前 12 票按范围 v1 仅运单号可送检，后 8 票按范围 v2 增加脱敏联系电话（其中 2 票原值为空）；
页面第 21 行是与第 15 票同号的重复行，用于验证重采只能按样本 UID 匹配原行。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

EXEC_BATCH_NO = "EXEC-20261120-01"
TASK_NO = "ROBO-0003"
QC_GROUP = "质检一组"
CARRIER = "顺捷物流"

# 字段 -> 脱敏器登记在服务层，这里只声明字段清单与主键字段
WAYBILL_FIELD = "运单号"
PHONE_FIELD = "联系电话"
SHARE_FIELDS = [WAYBILL_FIELD, PHONE_FIELD]

LEVEL_PLAIN = "明文"
LEVEL_MASKED = "脱敏"
LEVEL_RESTRICTED = "受限"

BATCH_PENDING = "待签收"
BATCH_SIGNED = "已签收"


def _scan_time(seq: int) -> str:
    if seq <= 12:
        minute = seq - 1
        return f"2026-11-20 09:{minute:02d}:00"
    # 授权在 10:30 扩大，后 8 票都在扩大之后扫描
    minute = 35 + (seq - 13) * 2
    return f"2026-11-20 10:{minute:02d}:00"


def build_exec_samples() -> list[dict[str, Any]]:
    """原执行批次：页面样本原值留档，联系电话原值只存在这张表。"""
    rows: list[dict[str, Any]] = []
    empty_phone_seq = {17, 19}  # 后 8 票里两票漏填联系电话
    for seq in range(1, 21):
        raw_phone = "" if seq in empty_phone_seq else f"139{seq:08d}"
        rows.append({
            "id": seq,
            "样本UID": f"SMP-{seq:03d}",
            "执行批次": EXEC_BATCH_NO,
            "页面行号": seq,
            "扫描序号": seq,
            "运单号": f"YD2026112{seq:03d}",
            "联系电话原值": raw_phone,
            "采集时间": _scan_time(seq),
            "重复行标记": False,
            "关联样本UID": "",
            "重采历史": [],
        })
    # 页面第 21 行：与第 15 票同号的重复行，重采时不得借这一行重新交付
    rows.append({
        "id": 21,
        "样本UID": "SMP-021",
        "执行批次": EXEC_BATCH_NO,
        "页面行号": 21,
        "扫描序号": 21,
        "运单号": "YD2026112015",
        "联系电话原值": "13900000015",
        "采集时间": "2026-11-20 11:05:00",
        "重复行标记": True,
        "关联样本UID": "SMP-015",
        "重采历史": [],
    })
    return rows


def build_scopes() -> list[dict[str, Any]]:
    """共享范围版本：v1 电话受限，v2 放宽为脱敏；每批交付冻结自己的快照。"""
    return [
        {
            "id": 1,
            "status": "已替代",
            "pending": False,
            "abnormal": False,
            "范围编号": "SCP-0001",
            "版本号": 1,
            "质检组": QC_GROUP,
            "承运方": CARRIER,
            "生效时间": "2026-11-20 08:30:00",
            "失效时间": "2026-11-20 10:30:00",
            "字段口径": [
                {"字段": WAYBILL_FIELD, "共享级别": LEVEL_PLAIN},
                {"字段": PHONE_FIELD, "共享级别": LEVEL_RESTRICTED},
            ],
            "版本说明": "首份送检口径：仅运单号获准送检，联系电话受控不交付",
        },
        {
            "id": 2,
            "status": "生效中",
            "pending": True,
            "abnormal": False,
            "范围编号": "SCP-0002",
            "版本号": 2,
            "质检组": QC_GROUP,
            "承运方": CARRIER,
            "生效时间": "2026-11-20 10:30:00",
            "失效时间": "",
            "字段口径": [
                {"字段": WAYBILL_FIELD, "共享级别": LEVEL_PLAIN},
                {"字段": PHONE_FIELD, "共享级别": LEVEL_MASKED},
            ],
            "版本说明": "承运方采到一半扩大授权：联系电话可按隐去中间四位脱敏交付",
        },
    ]


def _scope_map(scope_row: dict[str, Any]) -> dict[str, str]:
    return {item["字段"]: item["共享级别"] for item in scope_row["字段口径"]}


def build_tables() -> dict[str, list[dict[str, Any]]]:
    """生成 rpa_share 域的四张表（含已签收的首份清单与扩权后的第二份清单）。"""
    exec_samples = build_exec_samples()
    scopes = build_scopes()
    scope_v1 = scopes[0]
    scope_v2 = scopes[1]

    batches: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    record_id = 0

    def add_batch(
        batch_no: str,
        name: str,
        scope_row: dict[str, Any],
        seq_range: tuple[int, int],
        batch_status: str,
        created_at: str,
        signed_at: str,
    ) -> None:
        nonlocal record_id
        level_map = _scope_map(scope_row)
        readable = [f for f, level in level_map.items() if level != LEVEL_RESTRICTED]
        chosen = [s for s in exec_samples if seq_range[0] <= s["扫描序号"] <= seq_range[1] and not s["重复行标记"]]
        batch_id = len(batches) + 1
        batches.append({
            "id": batch_id,
            "status": batch_status,
            "pending": batch_status == BATCH_PENDING,
            "abnormal": False,
            "数据集编号": batch_no,
            "数据集名称": name,
            "关联任务": TASK_NO,
            "执行批次": EXEC_BATCH_NO,
            "质检组": QC_GROUP,
            "范围编号": scope_row["范围编号"],
            "范围快照": deepcopy(scope_row["字段口径"]),
            "可读字段": "、".join(readable),
            "样本票数": len(chosen),
            "生成时间": created_at,
            "签收时间": signed_at,
        })
        for sample in chosen:
            record_id += 1
            field_detail: dict[str, dict[str, Any]] = {}
            for field, level in level_map.items():
                raw = sample["运单号"] if field == WAYBILL_FIELD else sample["联系电话原值"]
                if level == LEVEL_RESTRICTED:
                    field_detail[field] = {"交付值": None, "口径": "未授权", "共享级别": level}
                    continue
                if raw in (None, ""):
                    field_detail[field] = {"交付值": "", "口径": "原值为空", "共享级别": level}
                elif level == LEVEL_MASKED and field == PHONE_FIELD:
                    field_detail[field] = {"交付值": _mask_phone(raw), "口径": "脱敏可读", "共享级别": level}
                else:
                    field_detail[field] = {"交付值": raw, "口径": "明文可读", "共享级别": level}
            phone_basis = field_detail[PHONE_FIELD]["口径"]
            records.append({
                "id": record_id,
                "status": batch_status,
                "pending": False,
                "abnormal": False,
                "数据集编号": batch_no,
                "样本UID": sample["样本UID"],
                "执行批次": sample["执行批次"],
                "页面行号": sample["页面行号"],
                "扫描序号": sample["扫描序号"],
                "运单号": field_detail[WAYBILL_FIELD]["交付值"],
                "联系电话": field_detail[PHONE_FIELD]["交付值"],
                "电话口径": phone_basis,
                "字段明细": field_detail,
            })

    add_batch(
        "RPS-0001",
        "出库运单首份送检清单（12票）",
        scope_v1,
        (1, 12),
        BATCH_SIGNED,
        "2026-11-20 09:30:00",
        "2026-11-20 09:45:00",
    )
    add_batch(
        "RPS-0002",
        "出库运单扩权后送检清单（8票）",
        scope_v2,
        (13, 20),
        BATCH_PENDING,
        "2026-11-20 11:10:00",
        "",
    )

    return {
        "rpa_share": batches,
        "rpa_share_scope": scopes,
        "rpa_share_exec_sample": exec_samples,
        "rpa_share_record": records,
    }


def _mask_phone(raw: str) -> str:
    """联系电话脱敏：保留前三位与后四位，中间四位以 * 替代。"""
    if len(raw) == 11:
        return f"{raw[:3]}****{raw[-4:]}"
    return "*" * len(raw)
