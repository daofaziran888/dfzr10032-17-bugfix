# 多源数据采集与RPA自动化平台

面向网页抓取、API接入、增量采集、RPA流程编排、数据校验与采集监控的数据工程平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 数据源配置 | `datasource` | 数据源 | 源端编号、连接类型、接入地址 |
| 网页采集规则 | `crawler` | 采集规则 | 规则编号、目标网址、页面选择器 |
| API接入管理 | `apiclient` | API客户端 | 客户端编号、接口名称、请求方法 |
| 增量采集 | `incremental` | 增量游标 | 游标编号、来源标识、增量字段 |
| RPA任务编排 | `robot_task` | RPA任务 | 任务编号、任务名称、页面定位器 |
| RPA共享字段数据集 | `rpa_share` | 共享批次/范围版本/交付记录/执行留档 | 数据集编号、范围快照、样本UID、核对行号 |
| 数据接入通道 | `ingestion` | 接入通道 | 通道编号、通道名称、输入格式 |
| 格式解析器 | `parser` | 解析配置 | 解析编号、输入格式、输出格式 |
| 采集结果校验 | `validator` | 校验规则 | 规则编号、校验字段、校验类型 |
| 采集去重 | `dedup` | 去重策略 | 策略编号、输入来源、去重键 |
| 采集调度 | `schedule` | 调度计划 | 计划编号、关联任务、调度周期 |
| 采集监控 | `monitor` | 监控面板 | 面板编号、采集源总数、今日采集量 |
| 采集日志 | `log_viewer` | 日志条目 | 日志编号、关联任务、日志级别 |
| 凭证管理 | `auth` | 认证凭证 | 凭证编号、凭证类型、关联数据源 |
| 采集转换管道 | `transform` | 转换节点 | 节点编号、输入来源、输出目标 |
| 数据流转编排 | `flow` | 流转管道 | 管道编号、管道名称、起始节点 |
| 数据血缘追踪 | `lineage` | 血缘关系 | 关系编号、上游节点、下游节点 |
| 采集报告 | `report` | 采集报告 | 报告编号、采集源、统计周期 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## RPA共享字段数据集（`rpa_share`）

RPA 任务页只登记结果字段，本模块负责把页面样本按「共享范围」解析成可交付质检组的数据集，
演示数据是同一批 20 票出库运单、采到一半承运方扩大授权的场景：

- **四张表（见 `app/rpa_share_data.py`）**：
  - `rpa_share_exec_sample` 原执行批次留档，受控字段（联系电话）原值只存在这里；
  - `rpa_share_scope` 共享范围版本（受限/脱敏/明文），范围只许放宽，收紧会被拒绝；
  - `rpa_share` 共享批次，生成时冻结范围快照，签收后口径与交付值不可变；
  - `rpa_share_record` 交付记录，只有可读字段（脱敏值）与核对行号
    （样本UID、页面行号、执行批次溯源），全链路不出现原值。
- **口径不变量**：
  - 字段由受限改为可共享时，已签收旧批次保持原快照，新权限生成可独立核对的新批次；
  - 重采只按内部样本UID匹配同一行，脱敏主键不参与匹配；页面重复行禁止借体重交原值；
  - 已签收批次不被重采回改，原值变化只留在执行批次；
  - 完整率经 `GET /api/ingestion/share-completeness` 由数据接入通道调用，
    只把本次授权字段计入分母，并区分「已填 / 原值为空 / 未授权」；
  - 返查 `POST /api/rpa_share/recheck` 逐票回放送检依据、核对行号与清单冻结时拿到的值。
- 后端测试：`cd backend && .venv/bin/python -m pytest tests/`
  （13 个用例覆盖原值不泄露、范围放宽、重采匹配、完整率与签收冻结等不变量）。
