<template>
  <section class="page" data-module="rpa_share">
    <header class="page-head">
      <div>
        <h2>RPA共享字段数据集</h2>
        <p class="page-desc">
          按共享范围解析 RPA 页面样本，只交付可读字段与核对行号；受控字段原值留在原执行批次。
          范围放宽生成新版本，已签收旧清单口径冻结，新权限走可独立核对的新共享批次。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="resetDemo">重置演示数据</button>
        <button class="btn primary" type="button" @click="openGenerate">生成共享批次</button>
      </div>
    </header>

    <div class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-item"
        :class="{ active: activeTab === tab.key }"
        type="button"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>

    <!-- 页签一：共享批次 -->
    <div v-if="activeTab === 'batches'">
      <div class="stat-row">
        <article v-for="item in stats" :key="item.label" class="stat-card">
          <span class="stat-label">{{ item.label }}</span>
          <strong class="stat-value">{{ item.value }}</strong>
        </article>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in batchColumns" :key="column">{{ column }}</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in batches" :key="String(row.id)">
            <td v-for="column in batchColumns" :key="column">{{ row[column] || '—' }}</td>
            <td>
              <span class="badge" :class="row.status === '已签收' ? 'signed' : 'masked'">{{ row.status }}</span>
            </td>
            <td class="row-actions">
              <button class="link" type="button" @click="viewRecords(row)">交付记录</button>
              <button class="link" type="button" @click="viewCompleteness(row)">完整率</button>
              <button
                v-if="row.status !== '已签收'"
                class="link"
                type="button"
                @click="signBatch(row)"
              >签收清单</button>
            </td>
          </tr>
          <tr v-if="!batches.length">
            <td :colspan="batchColumns.length + 2" class="empty-state">暂无共享批次，可先生成一份共享数据集</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 页签二：交付记录（只读，无原值） -->
    <div v-if="activeTab === 'records'">
      <form class="filter-bar" @submit.prevent="loadRecords">
        <label class="filter-item">
          <span>数据集编号</span>
          <select v-model="recordFilter.dataset_no">
            <option value="">全部批次</option>
            <option v-for="b in batches" :key="b.数据集编号" :value="b.数据集编号">{{ b.数据集编号 }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>运单号</span>
          <input v-model="recordFilter.keyword" placeholder="按运单号检索" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>
      <p class="muted-text">交付侧仅含可读字段与核对行号（样本UID / 页面行号 / 执行批次溯源），不含受控字段原值。</p>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in recordColumns" :key="column">{{ column }}</th>
            <th>电话口径</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in records" :key="String(row.id)">
            <td v-for="column in recordColumns" :key="column">{{ row[column] === null || row[column] === '' ? '—' : row[column] }}</td>
            <td><span class="badge" :class="basisClass(row.电话口径)">{{ row.电话口径 }}</span></td>
          </tr>
          <tr v-if="!records.length">
            <td :colspan="recordColumns.length + 1" class="empty-state">暂无交付记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 页签三：完整率明细 -->
    <div v-if="activeTab === 'completeness'">
      <form class="filter-bar" @submit.prevent="loadCompleteness">
        <label class="filter-item">
          <span>选择共享批次</span>
          <select v-model="completenessNo">
            <option v-for="b in batches" :key="b.数据集编号" :value="b.数据集编号">
              {{ b.数据集编号 }}（{{ b.数据集名称 }}）
            </option>
          </select>
        </label>
        <button class="btn" type="submit">计算完整率</button>
      </form>
      <p class="muted-text">
        数据接入通道按本批次冻结的共享权限计算：授权字段才计入分母，原值为空与未授权分别列示。
      </p>
      <template v-if="completeness">
        <div class="stat-row">
          <article class="stat-card"><span class="stat-label">样本票数</span><strong class="stat-value">{{ completeness.样本票数 }}</strong></article>
          <article class="stat-card"><span class="stat-label">授权字段总数</span><strong class="stat-value">{{ completeness.授权字段总数 }}</strong></article>
          <article class="stat-card"><span class="stat-label">已填总数</span><strong class="stat-value">{{ completeness.已填总数 }}</strong></article>
          <article class="stat-card"><span class="stat-label">原值为空</span><strong class="stat-value">{{ completeness.原值为空总数 }}</strong></article>
          <article class="stat-card"><span class="stat-label">未授权字段</span><strong class="stat-value">{{ completeness.未授权字段总数 }}</strong></article>
          <article class="stat-card"><span class="stat-label">综合完整率</span><strong class="stat-value">{{ rateText(completeness.综合完整率) }}</strong></article>
        </div>
        <table class="data-table">
          <thead>
            <tr><th>字段</th><th>共享级别</th><th>是否计入</th><th>授权字段数</th><th>已填数</th><th>原值为空数</th><th>未授权数</th><th>完整率</th></tr>
          </thead>
          <tbody>
            <tr v-for="f in completeness.字段明细" :key="f.字段">
              <td>{{ f.字段 }}</td>
              <td><span class="badge" :class="levelClass(f.共享级别)">{{ f.共享级别 }}</span></td>
              <td>{{ f.是否计入 ? '计入' : '不计入' }}</td>
              <td>{{ f.授权字段数 }}</td>
              <td>{{ f.已填数 }}</td>
              <td>{{ f.原值为空数 }}</td>
              <td>{{ f.未授权数 }}</td>
              <td>{{ rateText(f.完整率) }}</td>
            </tr>
          </tbody>
        </table>
        <h4 style="margin:14px 0 6px;font-size:14px">逐票行明细（用于核对允许计入的字段与空值区分）</h4>
        <table class="data-table">
          <thead>
            <tr><th>样本UID</th><th>页面行号</th><th>运单号</th><th>电话交付值</th><th>电话口径</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in completeness.行明细" :key="r.样本UID">
              <td>{{ r.样本UID }}</td>
              <td>{{ r.页面行号 }}</td>
              <td>{{ r.逐字段交付值.运单号 }}</td>
              <td>{{ r.逐字段交付值.联系电话 === '' ? '—' : (r.逐字段交付值.联系电话 ?? '—') }}</td>
              <td><span class="badge" :class="basisClass(r.逐字段口径.联系电话)">{{ r.逐字段口径.联系电话 }}</span></td>
            </tr>
          </tbody>
        </table>
      </template>
    </div>

    <!-- 页签四：返查与重采 -->
    <div v-if="activeTab === 'recheck'">
      <div class="sub-card">
        <h4>漏填返查：逐票对上送检依据</h4>
        <form class="inline-form" @submit.prevent="runRecheck">
          <label>送检清单
            <select v-model="recheckNo">
              <option v-for="b in batches" :key="b.数据集编号" :value="b.数据集编号">
                {{ b.数据集编号 }}（{{ b.status }}）
              </option>
            </select>
          </label>
          <label style="min-width:320px">漏填票号（逗号或中文逗号分隔）
            <input v-model="recheckInput" placeholder="例如：YD2026112017,YD2026112019" />
          </label>
          <button class="btn primary" type="submit">发起返查</button>
        </form>
        <template v-if="recheckResult">
          <p class="muted-text" style="margin-top:8px">
            清单 {{ recheckResult.数据集编号 }} · {{ recheckResult.清单状态 }} ·
            签收时间 {{ recheckResult.签收时间 || '—' }} · 命中 {{ recheckResult.票量 }} 票
            <template v-if="recheckResult.清单外票号.length"> · 清单外票号：{{ recheckResult.清单外票号.join('、') }}</template>
          </p>
          <table class="data-table">
            <thead>
              <tr><th>运单号</th><th>样本UID</th><th>页面行号</th><th>字段</th><th>共享级别</th><th>口径</th><th>当时拿到的值</th></tr>
            </thead>
            <tbody>
              <template v-for="t in recheckResult.返查明细" :key="t.运单号">
                <tr v-for="(detail, field) in t.逐字段依据" :key="t.运单号 + field">
                  <td>{{ t.运单号 }}</td>
                  <td>{{ t.样本UID }}</td>
                  <td>{{ t.页面行号 }}</td>
                  <td>{{ field }}</td>
                  <td><span class="badge" :class="levelClass(detail.共享级别)">{{ detail.共享级别 }}</span></td>
                  <td><span class="badge" :class="basisClass(detail.口径)">{{ detail.口径 }}</span></td>
                  <td>{{ detail.当时交付值 === null || detail.当时交付值 === '' ? '—' : detail.当时交付值 }}</td>
                </tr>
              </template>
            </tbody>
          </table>
        </template>
      </div>

      <div class="sub-card">
        <h4>按样本UID重采同一行（脱敏主键不参与匹配，重复行禁止借体重交原值）</h4>
        <form class="inline-form" @submit.prevent="runRecollect">
          <label>样本UID（必填）
            <input v-model="recollectForm.样本UID" placeholder="例如 SMP-017" required />
          </label>
          <label>新运单号（可选）
            <input v-model="recollectForm.运单号" placeholder="留空表示不更新" />
          </label>
          <label>新联系电话原值（可选，留空表示清空）
            <input v-model="recollectForm.联系电话" placeholder="原值只回写执行批次" />
          </label>
          <button class="btn primary" type="submit">提交重采</button>
        </form>
      </div>
    </div>

    <!-- 页签五：执行批次留档与共享范围 -->
    <div v-if="activeTab === 'archive'">
      <div class="sub-card">
        <h4>共享范围版本（只许放宽，已交付批次冻结各自快照）</h4>
        <form class="inline-form" @submit.prevent="widenScope">
          <label>字段
            <select v-model="widenForm.field">
              <option value="联系电话">联系电话</option>
              <option value="运单号">运单号</option>
            </select>
          </label>
          <label>新共享级别
            <select v-model="widenForm.level">
              <option value="脱敏">脱敏</option>
              <option value="明文">明文</option>
              <option value="受限">受限（收紧，应被拒绝）</option>
            </select>
          </label>
          <label style="min-width:260px">版本说明
            <input v-model="widenForm.remark" placeholder="例如：承运方扩大质检组授权" />
          </label>
          <button class="btn primary" type="submit">登记新版本</button>
        </form>
        <table class="data-table" style="margin-top:10px">
          <thead><tr><th>范围编号</th><th>版本</th><th>状态</th><th>生效时间</th><th>字段口径</th><th>说明</th></tr></thead>
          <tbody>
            <tr v-for="s in scopes" :key="s.范围编号">
              <td>{{ s.范围编号 }}</td>
              <td>v{{ s.版本号 }}</td>
              <td>{{ s.status }}</td>
              <td>{{ s.生效时间 }}</td>
              <td>
                <span v-for="item in s.字段口径" :key="item.字段" class="badge" :class="levelClass(item.共享级别)" style="margin-right:6px">
                  {{ item.字段 }}·{{ item.共享级别 }}
                </span>
              </td>
              <td>{{ s.版本说明 }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="sub-card">
        <h4>原执行批次留档（内部视图：受控字段原值只存在这里，不随共享数据集交付）</h4>
        <form class="filter-bar" @submit.prevent="loadExecSamples">
          <label class="filter-item"><span>运单号检索</span><input v-model="execKeyword" placeholder="按运单号检索" /></label>
          <button class="btn" type="submit">查询</button>
        </form>
        <table class="data-table">
          <thead><tr><th>样本UID</th><th>页面行号</th><th>扫描序号</th><th>运单号</th><th>联系电话原值</th><th>重复行</th><th>重采次数</th></tr></thead>
          <tbody>
            <tr v-for="s in execSamples" :key="s.样本UID">
              <td>{{ s.样本UID }}</td>
              <td>{{ s.页面行号 }}</td>
              <td>{{ s.扫描序号 }}</td>
              <td>{{ s.运单号 }}</td>
              <td>{{ s.联系电话原值 || '—' }}</td>
              <td>
                <span v-if="s.重复行标记" class="badge restricted">重复行→{{ s.关联样本UID }}</span>
                <span v-else>—</span>
              </td>
              <td>{{ s.重采历史?.length ?? 0 }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 生成共享批次弹窗 -->
    <Teleport to="body">
      <div v-if="showGenerate" class="modal-overlay" @click.self="showGenerate = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>按当前共享范围生成共享批次</h3>
            <button class="btn ghost" type="button" @click="showGenerate = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitGenerate">
            <label class="modal-field"><span>数据集名称</span><input v-model="generateForm.数据集名称" required /></label>
            <label class="modal-field"><span>扫描序号起</span><input v-model.number="generateForm.扫描序号起" type="number" required /></label>
            <label class="modal-field"><span>扫描序号止</span><input v-model.number="generateForm.扫描序号止" type="number" required /></label>
            <p class="muted-text">将按最新生效的共享范围快照解析执行批次样本，原值不进入交付侧。</p>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showGenerate = false">取消</button>
              <button class="btn primary" type="submit">生成</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

interface BatchRow {
  id: number
  status: string
  数据集编号: string
  数据集名称: string
  执行批次: string
  范围编号: string
  范围快照: { 字段: string; 共享级别: string }[]
  可读字段: string
  样本票数: number
  生成时间: string
  签收时间: string
}
interface RecordRow {
  id: number
  数据集编号: string
  样本UID: string
  执行批次: string
  页面行号: number
  扫描序号: number
  运单号: string
  联系电话: string | null
  电话口径: string
}
interface ScopeRow {
  id: number
  status: string
  范围编号: string
  版本号: number
  生效时间: string
  字段口径: { 字段: string; 共享级别: string }[]
  版本说明: string
}
interface ExecRow {
  样本UID: string
  页面行号: number
  扫描序号: number
  运单号: string
  联系电话原值: string
  重复行标记: boolean
  关联样本UID: string
  重采历史: unknown[]
}
interface FieldBasis { 共享级别: string; 口径: string; 当时交付值: string | null }
interface RecheckTicket { 运单号: string; 样本UID: string; 页面行号: number; 逐字段依据: Record<string, FieldBasis> }
interface CompletenessReport {
  数据集编号: string
  样本票数: number
  授权字段总数: number
  已填总数: number
  原值为空总数: number
  未授权字段总数: number
  综合完整率: number | null
  字段明细: { 字段: string; 共享级别: string; 是否计入: boolean; 授权字段数: number; 已填数: number; 原值为空数: number; 未授权数: number; 完整率: number | null }[]
  行明细: { 样本UID: string; 页面行号: number; 逐字段交付值: Record<string, string | null>; 逐字段口径: Record<string, string> }[]
}
interface RecheckReport {
  数据集编号: string
  清单状态: string
  签收时间: string
  票量: number
  清单外票号: string[]
  返查明细: RecheckTicket[]
}
interface ActionResponse { ok: boolean; message?: string; entry?: unknown }

const ENDPOINT = '/api/rpa_share'
const tabs = [
  { key: 'batches', label: '共享批次' },
  { key: 'records', label: '交付记录（只读）' },
  { key: 'completeness', label: '完整率明细' },
  { key: 'recheck', label: '返查与重采' },
  { key: 'archive', label: '执行留档与共享范围' },
]
const activeTab = ref('batches')
const errorMessage = ref('')

const batchColumns: (keyof BatchRow)[] = ['数据集编号', '数据集名称', '执行批次', '范围编号', '可读字段', '样本票数', '生成时间', '签收时间']
const recordColumns: (keyof RecordRow)[] = ['数据集编号', '样本UID', '执行批次', '页面行号', '扫描序号', '运单号', '联系电话']
const batches = ref<BatchRow[]>([])
const records = ref<RecordRow[]>([])
const scopes = ref<ScopeRow[]>([])
const execSamples = ref<ExecRow[]>([])
const stats = ref([
  { label: '共享批次总数', value: 0 },
  { label: '待签收', value: 0 },
  { label: '已签收', value: 0 },
])

const recordFilter = ref<{ dataset_no: string; keyword: string }>({ dataset_no: '', keyword: '' })
const completenessNo = ref('RPS-0001')
const completeness = ref<CompletenessReport | null>(null)
const recheckNo = ref('RPS-0001')
const recheckInput = ref('YD2026112017,YD2026112019')
const recheckResult = ref<RecheckReport | null>(null)
const recollectForm = ref({ 样本UID: '', 运单号: '', 联系电话: '' })
const widenForm = ref({ field: '联系电话', level: '脱敏', remark: '' })
const execKeyword = ref('')
const showGenerate = ref(false)
const generateForm = ref<{ 数据集名称: string; 扫描序号起: number | null; 扫描序号止: number | null }>({
  数据集名称: '',
  扫描序号起: 1,
  扫描序号止: 12,
})

function levelClass(level: string): string {
  if (level === '明文') return 'plain'
  if (level === '脱敏') return 'masked'
  if (level === '受限') return 'restricted'
  return 'empty'
}

function basisClass(basis: string): string {
  if (basis === '明文可读') return 'plain'
  if (basis === '脱敏可读') return 'masked'
  if (basis === '未授权') return 'restricted'
  return 'empty'
}

function rateText(rate: number | null): string {
  return rate === null || rate === undefined ? '不计入' : `${(rate * 100).toFixed(2)}%`
}

async function callJson(path: string, init?: RequestInit): Promise<ActionResponse> {
  const response = await request(path, init)
  return response.json()
}

function fail(message: string) {
  errorMessage.value = message
}

async function loadBatches() {
  const response = await request(`${ENDPOINT}?size=200`)
  const payload = await response.json()
  batches.value = (payload.items ?? []) as BatchRow[]
  stats.value[0].value = batches.value.length
  stats.value[1].value = batches.value.filter((b) => b.status === '待签收').length
  stats.value[2].value = batches.value.filter((b) => b.status === '已签收').length
}

async function loadScopes() {
  const payload = await callJson(`${ENDPOINT}/scopes`)
  scopes.value = ((payload as { items?: ScopeRow[] }).items ?? []) as ScopeRow[]
}

async function loadRecords() {
  errorMessage.value = ''
  const params = new URLSearchParams({ size: '200' })
  if (recordFilter.value.dataset_no) params.set('dataset_no', recordFilter.value.dataset_no)
  if (recordFilter.value.keyword) params.set('keyword', recordFilter.value.keyword)
  const payload = await callJson(`${ENDPOINT}/records?${params.toString()}`)
  records.value = ((payload as { items?: RecordRow[] }).items ?? []) as RecordRow[]
}

async function loadCompleteness() {
  errorMessage.value = ''
  const response = await request(`/api/ingestion/share-completeness?dataset_no=${encodeURIComponent(completenessNo.value)}`)
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: '完整率计算失败' }))
    fail(detail.detail || '完整率计算失败')
    return
  }
  completeness.value = await response.json()
}

async function runRecheck() {
  errorMessage.value = ''
  const result = await callJson(`${ENDPOINT}/recheck`, {
    method: 'POST',
    body: JSON.stringify({ values: { 数据集编号: recheckNo.value, 票号: recheckInput.value } }),
  })
  if (!result.ok) {
    fail(result.message || '返查失败')
    recheckResult.value = null
    return
  }
  recheckResult.value = result.entry as RecheckReport
}

async function runRecollect() {
  errorMessage.value = ''
  const values: Record<string, string> = { 样本UID: recollectForm.value.样本UID }
  if (recollectForm.value.运单号) values.运单号 = recollectForm.value.运单号
  if (recollectForm.value.联系电话) values.联系电话 = recollectForm.value.联系电话
  const result = await callJson(`${ENDPOINT}/recollect`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  if (!result.ok) {
    fail(result.message || '重采失败')
    return
  }
  window.alert(result.message ?? '重采完成')
  await Promise.all([loadBatches(), loadRecords(), loadExecSamples()])
}

async function widenScope() {
  errorMessage.value = ''
  const result = await callJson(`${ENDPOINT}/scopes/widen`, {
    method: 'POST',
    body: JSON.stringify({
      values: { [widenForm.value.field]: widenForm.value.level, 备注: widenForm.value.remark },
    }),
  })
  if (!result.ok) {
    fail(result.message || '范围登记失败')
    return
  }
  await loadScopes()
}

async function loadExecSamples() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (execKeyword.value) params.set('keyword', execKeyword.value)
  const payload = await callJson(`${ENDPOINT}/exec_samples?${params.toString()}`)
  execSamples.value = ((payload as { items?: ExecRow[] }).items ?? []) as ExecRow[]
}

async function signBatch(row: BatchRow) {
  errorMessage.value = ''
  const result = await callJson(`${ENDPOINT}/${row.id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ values: { action: '签收清单' } }),
  })
  if (!result.ok) {
    fail(result.message || '签收失败')
    return
  }
  await loadBatches()
}

function viewRecords(row: BatchRow) {
  recordFilter.value.dataset_no = row.数据集编号
  activeTab.value = 'records'
  void loadRecords()
}

function viewCompleteness(row: BatchRow) {
  completenessNo.value = row.数据集编号
  activeTab.value = 'completeness'
  void loadCompleteness()
}

function openGenerate() {
  errorMessage.value = ''
  showGenerate.value = true
}

async function submitGenerate() {
  errorMessage.value = ''
  const result = await callJson(ENDPOINT, {
    method: 'POST',
    body: JSON.stringify({ values: { ...generateForm.value } }),
  })
  if (!result.ok) {
    fail(result.message || '生成失败')
    return
  }
  showGenerate.value = false
  await loadBatches()
}

async function resetDemo() {
  errorMessage.value = ''
  await callJson(`${ENDPOINT}/reset_demo`, { method: 'POST' })
  await Promise.all([loadBatches(), loadScopes(), loadRecords(), loadExecSamples()])
}

function switchTab(key: string) {
  activeTab.value = key
  errorMessage.value = ''
  if (key === 'records') void loadRecords()
  if (key === 'completeness') void loadCompleteness()
  if (key === 'archive') void Promise.all([loadScopes(), loadExecSamples()])
}

onMounted(async () => {
  await Promise.all([loadBatches(), loadScopes(), loadRecords(), loadExecSamples()])
})
</script>
