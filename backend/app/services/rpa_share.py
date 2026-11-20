"""RPA共享字段数据集业务规则。

口径要点（业务约束全部收在本层，路由层不做判断）：
1. 受控字段原值只存在执行批次样本表，共享批次与交付记录里永远拿不到原值；
2. 共享范围按版本放宽，已签收批次冻结自己的范围快照，改口径不回改旧批次；
3. 重采按样本 UID 匹配同一行，脱敏主键不参与匹配，重复行不能借体重交原值；
4. 完整率只把本次授权字段计入分母，并与「原值为空」区分开；
5. 返查逐票回放到送检清单（批次）冻结时的口径与交付值。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.rpa_share_data import (
    BATCH_PENDING,
    BATCH_SIGNED,
    CARRIER,
    LEVEL_MASKED,
    LEVEL_PLAIN,
    LEVEL_RESTRICTED,
    PHONE_FIELD,
    QC_GROUP,
    SHARE_FIELDS,
    TASK_NO,
    WAYBILL_FIELD,
    build_tables,
)
from app.store import store

MODULE = "rpa_share"
SCOPE_MODULE = "rpa_share_scope"
EXEC_MODULE = "rpa_share_exec_sample"
RECORD_MODULE = "rpa_share_record"

# 放宽方向：受限 → 脱敏/明文，脱敏 → 明文；同级别视为无变化，收紧一律拒绝
LOOSEN_ORDER = {LEVEL_RESTRICTED: 0, LEVEL_MASKED: 1, LEVEL_PLAIN: 2}


def mask_phone(raw: str) -> str:
    """联系电话脱敏：保留前三位与后四位，隐去中间四位。"""
    if not raw:
        return ""
    if len(raw) == 11:
        return f"{raw[:3]}****{raw[-4:]}"
    return "*" * len(raw)


MASKERS = {PHONE_FIELD: mask_phone}


class RpaShareService:
    # ---------- 共享批次（交付数据集） ----------

    def list_batches(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        extra: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("数据集编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if extra:
            for field, val in extra.items():
                rows = [row for row in rows if val in str(row.get(field, ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_batch(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def find_batch_by_no(self, dataset_no: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if row.get("数据集编号") == dataset_no:
                return row
        return None

    def list_records(
        self,
        dataset_no: str | None = None,
        *,
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """交付记录：只有可读字段值与核对行号，不含任何原值。"""
        rows = store.rows(RECORD_MODULE)
        if dataset_no:
            rows = [row for row in rows if row.get("数据集编号") == dataset_no]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("运单号", ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def sign_batch(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        """签收共享批次：签收后快照与交付记录冻结，任何重采都不再回改。"""
        batch = store.find(MODULE, entry_id)
        if batch is None:
            return None, f"共享数据集 {entry_id} 不存在或已归档"
        if batch["status"] == BATCH_SIGNED:
            return None, "该清单已签收，口径与交付值已冻结，不能重复签收"
        batch["status"] = BATCH_SIGNED
        batch["pending"] = False
        for record in store.rows(RECORD_MODULE):
            if record["数据集编号"] == batch["数据集编号"]:
                record["status"] = BATCH_SIGNED
        return batch, f"共享数据集 {batch['数据集编号']} 已签收，交付口径已冻结"

    # ---------- 共享范围版本 ----------

    def list_scopes(self) -> list[dict[str, Any]]:
        return store.rows(SCOPE_MODULE)

    def latest_scope(self) -> dict[str, Any]:
        scopes = store.rows(SCOPE_MODULE)
        return max(scopes, key=lambda row: int(row["版本号"]))

    def widen_scope(self, field_levels: dict[str, str], remark: str) -> tuple[dict[str, Any] | None, str]:
        """登记新一版共享范围。只许放宽不许收紧；已交付批次保持原快照不动。"""
        unknown = [f for f in field_levels if f not in SHARE_FIELDS]
        if unknown:
            return None, f"字段不属于本数据集共享范围：{'、'.join(unknown)}"
        bad_level = [v for v in field_levels.values() if v not in LOOSEN_ORDER]
        if bad_level:
            return None, "共享级别只允许：受限、脱敏、明文"
        current = self.latest_scope()
        current_map = {item["字段"]: item["共享级别"] for item in current["字段口径"]}
        tightened: list[str] = []
        unchanged = True
        for field, new_level in field_levels.items():
            old_level = current_map.get(field, LEVEL_RESTRICTED)
            if LOOSEN_ORDER[new_level] < LOOSEN_ORDER[old_level]:
                tightened.append(field)
            if new_level != old_level:
                unchanged = False
        if tightened:
            return None, f"共享范围只能放宽不能收紧，以下字段被收紧：{'、'.join(tightened)}"
        if unchanged:
            return None, "新口径与当前版本完全一致，无需生成新版本"

        rows = store.rows(SCOPE_MODULE)
        new_version = int(current["版本号"]) + 1
        merged = dict(current_map)
        merged.update(field_levels)
        current["status"] = "已替代"
        current["pending"] = False
        scope = {
            "id": max(int(row["id"]) for row in rows) + 1,
            "status": "生效中",
            "pending": True,
            "abnormal": False,
            "范围编号": f"SCP-{new_version:04d}",
            "版本号": new_version,
            "质检组": QC_GROUP,
            "承运方": CARRIER,
            "生效时间": "2026-11-20 11:15:00",
            "失效时间": "",
            "字段口径": [{"字段": f, "共享级别": merged[f]} for f in SHARE_FIELDS],
            "版本说明": remark or f"第 {new_version} 版共享范围",
        }
        rows.append(scope)
        return scope, f"已生成共享范围 v{new_version}，历史批次仍按各自快照口径核对"

    # ---------- 生成共享批次 ----------

    def generate_batch(self, name: str, seq_from: int, seq_to: int) -> tuple[dict[str, Any] | None, str]:
        """按当前共享范围解析执行批次样本，生成一份可独立核对的新共享批次。"""
        if seq_to < seq_from:
            return None, "扫描序号区间不合法"
        scope = self.latest_scope()
        samples = [
            row for row in store.rows(EXEC_MODULE)
            if seq_from <= int(row["扫描序号"]) <= seq_to and not row["重复行标记"]
        ]
        if not samples:
            return None, "区间内没有可解析的页面样本"
        batches = store.rows(MODULE)
        new_id = max(int(row["id"]) for row in batches) + 1
        dataset_no = f"RPS-{new_id:04d}"
        level_map = {item["字段"]: item["共享级别"] for item in scope["字段口径"]}
        readable = [f for f, level in level_map.items() if level != LEVEL_RESTRICTED]
        batch = {
            "id": new_id,
            "status": BATCH_PENDING,
            "pending": True,
            "abnormal": False,
            "数据集编号": dataset_no,
            "数据集名称": name,
            "关联任务": TASK_NO,
            "执行批次": samples[0]["执行批次"],
            "质检组": QC_GROUP,
            "范围编号": scope["范围编号"],
            "范围快照": deepcopy(scope["字段口径"]),
            "可读字段": "、".join(readable),
            "样本票数": len(samples),
            "生成时间": "2026-11-20 11:20:00",
            "签收时间": "",
        }
        batches.append(batch)
        records = store.rows(RECORD_MODULE)
        next_id = max((int(row["id"]) for row in records), default=0) + 1
        for sample in samples:
            record = self._project_record(next_id, dataset_no, sample, level_map)
            records.append(record)
            next_id += 1
        return batch, f"已生成共享数据集 {dataset_no}，含 {len(samples)} 票，原值未出交付侧"

    def _project_record(
        self,
        record_id: int,
        dataset_no: str,
        sample: dict[str, Any],
        level_map: dict[str, str],
    ) -> dict[str, Any]:
        """把一条执行样本按范围快照投影成交付记录；原值在此被挡下或脱敏。"""
        field_detail: dict[str, dict[str, Any]] = {}
        for field in SHARE_FIELDS:
            level = level_map.get(field, LEVEL_RESTRICTED)
            raw = sample["运单号"] if field == WAYBILL_FIELD else sample["联系电话原值"]
            if level == LEVEL_RESTRICTED:
                field_detail[field] = {"交付值": None, "口径": "未授权", "共享级别": level}
            elif raw in (None, ""):
                field_detail[field] = {"交付值": "", "口径": "原值为空", "共享级别": level}
            elif level == LEVEL_MASKED:
                field_detail[field] = {
                    "交付值": MASKERS[field](raw),
                    "口径": "脱敏可读",
                    "共享级别": level,
                }
            else:
                field_detail[field] = {"交付值": raw, "口径": "明文可读", "共享级别": level}
        return {
            "id": record_id,
            "status": BATCH_PENDING,
            "pending": False,
            "abnormal": False,
            "数据集编号": dataset_no,
            "样本UID": sample["样本UID"],
            "执行批次": sample["执行批次"],
            "页面行号": sample["页面行号"],
            "扫描序号": sample["扫描序号"],
            "运单号": field_detail[WAYBILL_FIELD]["交付值"],
            "联系电话": field_detail[PHONE_FIELD]["交付值"],
            "电话口径": field_detail[PHONE_FIELD]["口径"],
            "字段明细": field_detail,
        }

    # ---------- 重采：按样本 UID 匹配同一行 ----------

    def recollect(self, sample_uid: str, new_values: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
        """重采同一行。

        - 只能按样本 UID 定位，脱敏后的运单号/电话不参与匹配；
        - 指向重复行的重采请求直接拒绝，防止借重复行重新交付原值；
        - 原值只更新执行批次留档；已签收批次不回改，待签收批次按现范围重新投影。
        """
        target = None
        for row in store.rows(EXEC_MODULE):
            if row["样本UID"] == sample_uid:
                target = row
                break
        if target is None:
            return None, f"样本 {sample_uid} 不在原执行批次中，无法重采"
        if target["重复行标记"]:
            return None, "该页面行是重复行，重采必须回到原样本UID，不能借重复行重新交付原值"

        history = target.setdefault("重采历史", [])
        before = {WAYBILL_FIELD: target["运单号"], PHONE_FIELD: target["联系电话原值"]}
        changed: dict[str, str] = {}
        if new_values.get(WAYBILL_FIELD):
            target["运单号"] = str(new_values[WAYBILL_FIELD]).strip()
            changed[WAYBILL_FIELD] = "已更新"
        if PHONE_FIELD in new_values:
            target["联系电话原值"] = str(new_values.get(PHONE_FIELD) or "").strip()
            changed[PHONE_FIELD] = "已更新"
        history.append({"重采前": before, "变更": changed or "无变更", "重采时间": "2026-11-20 11:30:00"})

        affected_batches: list[str] = []
        for record in store.rows(RECORD_MODULE):
            if record["样本UID"] != sample_uid:
                continue
            batch = self.find_batch_by_no(record["数据集编号"])
            if batch is None or batch["status"] == BATCH_SIGNED:
                # 已签收旧清单保持原口径，原值变化不外溢到旧交付
                continue
            level_map = {item["字段"]: item["共享级别"] for item in batch["范围快照"]}
            fresh = self._project_record(record["id"], record["数据集编号"], target, level_map)
            record.clear()
            record.update(fresh)
            affected_batches.append(record["数据集编号"])
        return target, (
            f"样本 {sample_uid} 已按UID匹配重采，原值仅更新执行批次留档；"
            f"影响待签收批次：{('、'.join(sorted(set(affected_batches))) or '无')}，"
            "已签收批次不回改"
        )

    # ---------- 完整率明细 ----------

    def completeness(self, dataset_no: str) -> dict[str, Any]:
        """按该批次冻结的共享权限计算完整率：授权字段才计入，空值与未授权分开列示。"""
        batch = self.find_batch_by_no(dataset_no)
        if batch is None:
            return {"ok": False, "message": f"共享数据集 {dataset_no} 不存在"}
        level_map = {item["字段"]: item["共享级别"] for item in batch["范围快照"]}
        records = [r for r in store.rows(RECORD_MODULE) if r["数据集编号"] == dataset_no]
        fields_report: list[dict[str, Any]] = []
        total_authorized = 0
        total_filled = 0
        total_empty = 0
        total_unauthorized = 0
        for field in SHARE_FIELDS:
            level = level_map.get(field, LEVEL_RESTRICTED)
            if level == LEVEL_RESTRICTED:
                item = {
                    "字段": field,
                    "共享级别": level,
                    "是否计入": False,
                    "授权字段数": 0,
                    "已填数": 0,
                    "原值为空数": len(records),
                    "未授权数": len(records),
                    "完整率": None,
                }
                total_unauthorized += len(records)
            else:
                detail_key = field
                filled = sum(1 for r in records if r["字段明细"][detail_key]["口径"] in ("明文可读", "脱敏可读"))
                empty = sum(1 for r in records if r["字段明细"][detail_key]["口径"] == "原值为空")
                authorized = len(records)
                total_authorized += authorized
                total_filled += filled
                total_empty += empty
                item = {
                    "字段": field,
                    "共享级别": level,
                    "是否计入": True,
                    "授权字段数": authorized,
                    "已填数": filled,
                    "原值为空数": empty,
                    "未授权数": 0,
                    "完整率": round(filled / authorized, 4) if authorized else None,
                }
            fields_report.append(item)
        rows_report = [
            {
                "样本UID": r["样本UID"],
                "页面行号": r["页面行号"],
                "运单号": r["运单号"],
                "逐字段口径": {f: r["字段明细"][f]["口径"] for f in SHARE_FIELDS},
                "逐字段交付值": {f: r["字段明细"][f]["交付值"] for f in SHARE_FIELDS},
            }
            for r in records
        ]
        return {
            "ok": True,
            "数据集编号": dataset_no,
            "范围编号": batch["范围编号"],
            "样本票数": len(records),
            "字段明细": fields_report,
            "授权字段总数": total_authorized,
            "已填总数": total_filled,
            "原值为空总数": total_empty,
            "未授权字段总数": total_unauthorized,
            "综合完整率": round(total_filled / total_authorized, 4) if total_authorized else None,
            "行明细": rows_report,
        }

    # ---------- 返查：逐票回放送检依据 ----------

    def recheck(self, dataset_no: str, waybill_nos: list[str]) -> dict[str, Any]:
        """质检员拿漏填票号返查：逐票给出送检依据、核对行号与清单冻结时拿到的值。"""
        batch = self.find_batch_by_no(dataset_no)
        if batch is None:
            return {"ok": False, "message": f"共享数据集 {dataset_no} 不存在"}
        records = {r["运单号"]: r for r in store.rows(RECORD_MODULE) if r["数据集编号"] == dataset_no}
        tickets: list[dict[str, Any]] = []
        missing: list[str] = []
        for no in waybill_nos:
            no = no.strip()
            if not no:
                continue
            record = records.get(no)
            if record is None:
                missing.append(no)
                continue
            tickets.append({
                "运单号": no,
                "样本UID": record["样本UID"],
                "页面行号": record["页面行号"],
                "扫描序号": record["扫描序号"],
                "送检清单": dataset_no,
                "范围编号": batch["范围编号"],
                "清单状态": batch["status"],
                "签收时间": batch["签收时间"],
                "逐字段依据": {
                    f: {
                        "共享级别": record["字段明细"][f]["共享级别"],
                        "口径": record["字段明细"][f]["口径"],
                        "当时交付值": record["字段明细"][f]["交付值"],
                    }
                    for f in SHARE_FIELDS
                },
            })
        return {
            "ok": True,
            "数据集编号": dataset_no,
            "范围编号": batch["范围编号"],
            "清单状态": batch["status"],
            "签收时间": batch["签收时间"],
            "票量": len(tickets),
            "返查明细": tickets,
            "清单外票号": missing,
        }

    # ---------- 执行批次留档（原值仅在此表） ----------

    def list_exec_samples(self, keyword: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(EXEC_MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("运单号", ""))]
        return rows

    def reset_demo_data(self) -> str:
        """把演示数据恢复到初始状态，方便反复演练扩权、重采与返查。"""
        tables = build_tables()
        for name, rows in tables.items():
            store.replace_rows(name, [deepcopy(row) for row in rows])
        return "RPA共享字段数据集演示数据已重置"


service = RpaShareService()
