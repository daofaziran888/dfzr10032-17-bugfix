"""RPA共享字段数据集接口。

路由层只做参数承接，口径判断全部在 ``RpaShareService``：
- 共享批次列表/签收/生成；交付记录只读；
- 共享范围版本查询与放宽；
- 完整率明细、漏填返查、按UID重采；
- 执行批次原值留档单独查看（原值仅该接口可见，不进入任何交付结构）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.rpa_share import service

router = APIRouter(prefix="/api/rpa_share", tags=["RPA共享字段数据集"])

LIST_FIELDS = ["数据集编号", "数据集名称", "执行批次", "范围编号", "可读字段", "样本票数", "生成时间", "签收时间"]
STATUSES = ["待签收", "已签收"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出共享数据集清单（批次元数据，不含交付记录与原值）。"""
    items, total = service.list_batches(page=1, size=10000)
    return {"module": "rpa_share", "total": total, "items": items}


@router.get("/scopes")
def list_scopes() -> dict[str, Any]:
    """共享范围版本列表：每批交付冻结的是自己的快照，不随新版本变化。"""
    return {"items": service.list_scopes()}


@router.post("/scopes/widen", response_model=ActionResult)
def widen_scope(payload: EntryPayload) -> ActionResult:
    """登记放宽后的共享范围（如联系电话由受限改为脱敏），生成独立新版本。"""
    values = dict(payload.values)
    remark = str(values.pop("备注", "") or "")
    field_levels = {str(k): str(v) for k, v in values.items()}
    scope, message = service.widen_scope(field_levels, remark)
    if scope is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=scope)


@router.get("/records", response_model=PageResult[dict])
def list_records(
    dataset_no: str | None = Query(default=None, description="按共享批次编号过滤交付记录"),
    keyword: str | None = Query(default=None, description="按运单号检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """交付记录：仅可读字段值与核对行号（样本UID/页面行号/执行批次溯源）。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_records(dataset_no, keyword=keyword, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/completeness")
def completeness(dataset_no: str = Query(..., description="共享批次编号")) -> dict[str, Any]:
    """完整率明细：只计本次授权字段，并区分已填、原值为空与未授权。"""
    result = service.completeness(dataset_no)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/recheck", response_model=ActionResult)
def recheck(payload: EntryPayload) -> ActionResult:
    """漏填返查：逐票回放送检依据、核对行号与清单冻结时拿到的值。"""
    dataset_no = str(payload.values.get("数据集编号") or "").strip()
    raw_nos = payload.values.get("票号") or []
    if isinstance(raw_nos, str):
        waybill_nos = [part for part in raw_nos.replace("，", ",").split(",")]
    else:
        waybill_nos = [str(part) for part in raw_nos]
    if not dataset_no:
        return ActionResult(ok=False, message="缺少必填字段：数据集编号")
    result = service.recheck(dataset_no, waybill_nos)
    if not result.get("ok"):
        return ActionResult(ok=False, message=result["message"])
    return ActionResult(ok=True, message=f"返查完成，命中 {result['票量']} 票", entry=result)


@router.post("/recollect", response_model=ActionResult)
def recollect(payload: EntryPayload) -> ActionResult:
    """按样本UID重采同一行：原值只回写执行批次，已签收批次不回改。"""
    sample_uid = str(payload.values.get("样本UID") or "").strip()
    if not sample_uid:
        return ActionResult(ok=False, message="缺少必填字段：样本UID")
    new_values = {
        key: str(payload.values[key])
        for key in ("运单号", "联系电话")
        if key in payload.values
    }
    sample, message = service.recollect(sample_uid, new_values)
    if sample is None:
        return ActionResult(ok=False, message=message)
    # 注意：回传的是执行批次留档行，其中含原值，仅用于内部核对，不进共享交付结构
    return ActionResult(ok=True, message=message, entry=sample)


@router.get("/exec_samples")
def list_exec_samples(keyword: str | None = Query(default=None, description="按运单号检索留档样本")) -> dict[str, Any]:
    """执行批次原值留档：受控字段原值只在此接口可见，共享批次与交付记录不含原值。"""
    return {
        "notice": "内部留档视图：联系电话原值仅留存于原执行批次，不随共享数据集交付",
        "items": service.list_exec_samples(keyword),
    }


@router.post("/reset_demo", response_model=ActionResult)
def reset_demo() -> ActionResult:
    """恢复演示数据初始状态（两版范围、两个批次、20票样本与重复行）。"""
    return ActionResult(ok=True, message=service.reset_demo_data())


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按数据集编号检索"),
    status: str | None = Query(default=None, description="待签收、已签收"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """共享数据集批次列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_batches(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单份共享数据集批次明细；不存在时给出可读的错误说明。"""
    entry = service.get_batch(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"共享数据集 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """按当前共享范围解析执行批次样本，生成一份新的共享批次。"""
    values = payload.values
    name = str(values.get("数据集名称") or "").strip()
    if not name:
        return ActionResult(ok=False, message="缺少必填字段：数据集名称")
    try:
        seq_from = int(values.get("扫描序号起", 0))
        seq_to = int(values.get("扫描序号止", 0))
    except (TypeError, ValueError):
        return ActionResult(ok=False, message="扫描序号起、止必须是整数")
    batch, message = service.generate_batch(name, seq_from, seq_to)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对共享批次执行签收；签收后范围快照与交付值冻结。"""
    action = str(payload.values.get("action") or "").strip()
    if action != "签收清单":
        return ActionResult(ok=False, message=f"动作「{action}」不属于RPA共享字段数据集可执行范围")
    entry, message = service.sign_batch(entry_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
