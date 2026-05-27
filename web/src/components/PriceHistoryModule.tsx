import { useState, useCallback, useEffect } from 'react'

interface PriceHistoryRecord {
  date: string
  price: number
  daily_sales: number
}

interface SkuHistory {
  sku_id: string
  name: string
  records: PriceHistoryRecord[]
}

const HISTORY_STORAGE_KEY = 'price_history_data'
const ERP_STORAGE_KEY = 'erp_sku_data'

function loadStoredHistory(): SkuHistory[] {
  try {
    const raw = sessionStorage.getItem(HISTORY_STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveHistory(data: SkuHistory[]) {
  sessionStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(data))
  // 同步合并到 ERP 数据的 price_history 字段
  mergeIntoErp(data)
}

function mergeIntoErp(historyData: SkuHistory[]) {
  try {
    const raw = sessionStorage.getItem(ERP_STORAGE_KEY)
    if (!raw) return
    const erpSkus = JSON.parse(raw)
    if (!Array.isArray(erpSkus)) return
    const historyMap = new Map(historyData.map((h) => [h.sku_id, h.records]))
    for (const sku of erpSkus) {
      const records = historyMap.get(sku.sku_id)
      if (records) {
        sku.price_history = records
      }
    }
    sessionStorage.setItem(ERP_STORAGE_KEY, JSON.stringify(erpSkus))
  } catch { /* ignore */ }
}

export function PriceHistoryModule() {
  const [history, setHistory] = useState<SkuHistory[]>(loadStoredHistory)
  const [message, setMessage] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => { saveHistory(history) }, [history])

  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setMessage('')
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const text = reader.result as string
        let data: SkuHistory[]
        if (file.name.endsWith('.csv')) {
          data = parseCsvHistory(text)
        } else {
          const parsed = JSON.parse(text)
          data = normalizeJson(parsed)
        }
        if (data.length === 0) {
          setMessage('未识别到有效数据，请检查格式')
          return
        }
        setHistory(data)
        const totalRecords = data.reduce((s, h) => s + h.records.length, 0)
        setMessage(`导入成功：${data.length} 个 SKU，共 ${totalRecords} 条历史记录`)
      } catch (err) {
        setMessage(`导入失败：${err instanceof Error ? err.message : '格式错误'}`)
      }
    }
    reader.readAsText(file, 'UTF-8')
    e.target.value = ''
  }, [])

  const handleLoadDemo = useCallback(async () => {
    try {
      const res = await fetch('/demo_price_history.json')
      if (!res.ok) throw new Error('无法加载演示数据')
      const parsed = await res.json()
      const data = normalizeJson(parsed)
      setHistory(data)
      const totalRecords = data.reduce((s, h) => s + h.records.length, 0)
      setMessage(`已加载演示数据：${data.length} 个 SKU，共 ${totalRecords} 条记录`)
    } catch {
      setMessage('加载演示数据失败，请确认 demo_price_history.json 在 web/public 目录下')
    }
  }, [])

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(history, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'price_history.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleClear = () => {
    setHistory([])
    setMessage('已清空历史数据')
  }

  const handleDeleteSku = (skuId: string) => {
    setHistory((prev) => prev.filter((h) => h.sku_id !== skuId))
  }

  return (
    <div className="erp-module">
      <div className="erp-module__header">
        <h2>价格历史数据</h2>
        <div className="erp-module__actions">
          <label className="btn btn-sm btn-feedback" style={{ cursor: 'pointer' }}>
            导入 JSON/CSV
            <input type="file" accept=".json,.csv" onChange={handleFileUpload} style={{ display: 'none' }} />
          </label>
          <button className="btn btn-sm btn-accept" onClick={handleLoadDemo}>
            加载演示数据
          </button>
          {history.length > 0 && (
            <>
              <button className="btn btn-sm btn-reject" onClick={handleExport}>导出</button>
              <button className="btn btn-sm btn-reject" onClick={handleClear}>清空</button>
            </>
          )}
        </div>
      </div>

      {message && <p className="erp-message">{message}</p>}

      {history.length > 0 && (
        <div className="erp-table-wrap">
          <table className="erp-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>名称</th>
                <th>记录数</th>
                <th>日期范围</th>
                <th>价格区间</th>
                <th>日销区间</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => {
                const prices = h.records.map((r) => r.price)
                const sales = h.records.map((r) => r.daily_sales)
                const dates = h.records.map((r) => r.date).sort()
                return (
                  <tr key={h.sku_id} style={{ cursor: 'pointer' }} onClick={() => setExpanded(expanded === h.sku_id ? null : h.sku_id)}>
                    <td className="tabular">{h.sku_id}</td>
                    <td>{h.name}</td>
                    <td className="tabular">{h.records.length}</td>
                    <td className="tabular">{dates[0]} ~ {dates[dates.length - 1]}</td>
                    <td className="tabular">{Math.min(...prices)} - {Math.max(...prices)}</td>
                    <td className="tabular">{Math.min(...sales)} - {Math.max(...sales)}</td>
                    <td><button className="btn-sm btn-reject" onClick={(e) => { e.stopPropagation(); handleDeleteSku(h.sku_id) }}>删除</button></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {expanded && (
        <div className="erp-table-wrap" style={{ marginTop: '1rem' }}>
          <h3 style={{ margin: '0 0 0.5rem' }}>{expanded} 明细</h3>
          <table className="erp-table">
            <thead>
              <tr><th>日期</th><th>价格</th><th>日销量</th></tr>
            </thead>
            <tbody>
              {history.find((h) => h.sku_id === expanded)?.records.map((r, i) => (
                <tr key={i}>
                  <td className="tabular">{r.date}</td>
                  <td className="tabular">{r.price}</td>
                  <td className="tabular">{r.daily_sales}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {history.length === 0 && (
        <div className="erp-empty">
          <p>暂无价格历史数据。上传后将自动合并到 ERP 数据中，供智能定价使用。</p>
          <p className="muted">JSON 格式：数组，每项含 sku_id, name, price_history: [{'{'}date, price, daily_sales{'}'}]</p>
          <p className="muted">CSV 格式：列名 sku_id, name, date, price, daily_sales（每行一条记录）</p>
        </div>
      )}
    </div>
  )
}

/** 解析 JSON：支持多种格式 */
function normalizeJson(parsed: unknown): SkuHistory[] {
  if (!Array.isArray(parsed)) return []
  // 格式1: [{sku_id, name, price_history: [...]}]
  if (parsed.length > 0 && Array.isArray((parsed[0] as Record<string, unknown>).price_history)) {
    return parsed.map((item: Record<string, unknown>) => ({
      sku_id: String(item.sku_id || ''),
      name: String(item.name || ''),
      records: ((item.price_history as Record<string, unknown>[]) || []).map((r) => ({
        date: String(r.date || ''),
        price: Number(r.price) || 0,
        daily_sales: Number(r.daily_sales) || 0,
      })),
    })).filter((h) => h.sku_id && h.records.length > 0)
  }
  // 格式2: [{sku_id, name, records: [...]}]
  if (parsed.length > 0 && Array.isArray((parsed[0] as Record<string, unknown>).records)) {
    return parsed.map((item: Record<string, unknown>) => ({
      sku_id: String(item.sku_id || ''),
      name: String(item.name || ''),
      records: ((item.records as Record<string, unknown>[]) || []).map((r) => ({
        date: String(r.date || ''),
        price: Number(r.price) || 0,
        daily_sales: Number(r.daily_sales) || 0,
      })),
    })).filter((h) => h.sku_id && h.records.length > 0)
  }
  return []
}

/** 解析 CSV：每行一条记录，按 sku_id 分组 */
function parseCsvHistory(text: string): SkuHistory[] {
  const lines = text.trim().split('\n')
  if (lines.length < 2) return []
  const headers = lines[0].split(',').map((h) => h.trim())
  const grouped = new Map<string, { name: string; records: PriceHistoryRecord[] }>()

  for (const line of lines.slice(1)) {
    const vals = line.split(',').map((v) => v.trim())
    const get = (key: string) => vals[headers.indexOf(key)] || ''
    const skuId = get('sku_id')
    if (!skuId) continue
    if (!grouped.has(skuId)) {
      grouped.set(skuId, { name: get('name') || skuId, records: [] })
    }
    grouped.get(skuId)!.records.push({
      date: get('date'),
      price: Number(get('price')) || 0,
      daily_sales: Number(get('daily_sales')) || 0,
    })
  }

  return Array.from(grouped.entries()).map(([sku_id, v]) => ({
    sku_id,
    name: v.name,
    records: v.records,
  }))
}
