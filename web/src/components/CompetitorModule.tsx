import React, { useState, useCallback, useEffect } from 'react'

interface CompetitorProduct {
  title: string
  price: number
  sales: number
}

interface CompetitorGroup {
  match_sku: string
  competitors: CompetitorProduct[]
}

const STORAGE_KEY = 'competitor_data'

function loadStored(): CompetitorGroup[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function save(groups: CompetitorGroup[]) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(groups))
}

export function CompetitorModule() {
  const [groups, setGroups] = useState<CompetitorGroup[]>(loadStored)
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  useEffect(() => { save(groups) }, [groups])

  const [form, setForm] = useState({
    match_sku: '',
    title: '',
    price: 0,
    sales: 0,
  })

  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setMessage('')
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const text = reader.result as string
        let data: CompetitorGroup[]
        if (file.name.endsWith('.csv')) {
          data = parseCsv(text)
        } else {
          const parsed = JSON.parse(text)
          data = Array.isArray(parsed) ? parsed : parsed.data || []
        }
        setGroups(data)
        const totalProducts = data.reduce((s, g) => s + g.competitors.length, 0)
        setMessage(`导入成功：${data.length} 个 SKU 分组，共 ${totalProducts} 条竞品`)
      } catch (err) {
        setMessage(`导入失败：${err instanceof Error ? err.message : '格式错误'}`)
      } finally {
        setUploading(false)
      }
    }
    reader.readAsText(file, 'UTF-8')
    e.target.value = ''
  }, [])

  const handleAdd = () => {
    const product: CompetitorProduct = { title: form.title, price: form.price, sales: form.sales }
    setGroups((prev) => {
      const existing = prev.find((g) => g.match_sku === form.match_sku)
      if (existing) {
        return prev.map((g) =>
          g.match_sku === form.match_sku
            ? { ...g, competitors: [...g.competitors, product] }
            : g
        )
      }
      return [...prev, { match_sku: form.match_sku, competitors: [product] }]
    })
    setForm({ match_sku: form.match_sku, title: '', price: 0, sales: 0 })
    setMessage('已添加 1 条竞品商品')
  }

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(groups, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'competitor_data.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleDeleteGroup = (idx: number) => {
    setGroups((prev) => prev.filter((_, i) => i !== idx))
    if (expandedIdx === idx) setExpandedIdx(null)
  }

  const handleDeleteProduct = (groupIdx: number, prodIdx: number) => {
    setGroups((prev) => prev.map((g, i) => {
      if (i !== groupIdx) return g
      const newComps = g.competitors.filter((_, j) => j !== prodIdx)
      return { ...g, competitors: newComps }
    }).filter((g) => g.competitors.length > 0))
  }

  return (
    <div className="erp-module">
      <div className="erp-module__header">
        <h2>竞品数据管理</h2>
        <div className="erp-module__actions">
          <label className="btn btn-sm btn-feedback" style={{ cursor: 'pointer' }}>
            {uploading ? '导入中...' : '导入 JSON/CSV'}
            <input type="file" accept=".json,.csv" onChange={handleFileUpload} style={{ display: 'none' }} />
          </label>
          <button className="btn btn-sm btn-accept" onClick={() => setShowAdd(!showAdd)}>
            {showAdd ? '取消' : '手动添加'}
          </button>
          {groups.length > 0 && (
            <button className="btn btn-sm btn-reject" onClick={handleExport}>导出 JSON</button>
          )}
        </div>
      </div>

      {message && <p className="erp-message">{message}</p>}

      {showAdd && (
        <div className="erp-add-form">
          <div className="erp-form-grid">
            <div className="form-group">
              <label>对标 SKU ID</label>
              <input type="text" placeholder="SKU2001" value={form.match_sku} onChange={(e) => setForm({ ...form, match_sku: e.target.value })} />
            </div>
            <div className="form-group">
              <label>竞品商品名</label>
              <input type="text" placeholder="天丝V领连衣裙 通勤气质" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </div>
            <div className="form-group">
              <label>价格 (元)</label>
              <input type="number" value={form.price || ''} onChange={(e) => setForm({ ...form, price: Number(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>月销量</label>
              <input type="number" value={form.sales || ''} onChange={(e) => setForm({ ...form, sales: Number(e.target.value) })} />
            </div>
          </div>
          <button className="btn btn-primary" disabled={!form.match_sku || !form.title} onClick={handleAdd}>
            添加竞品
          </button>
        </div>
      )}

      {groups.length > 0 && (
        <div className="erp-table-wrap">
          <table className="erp-table">
            <thead>
              <tr>
                <th>对标 SKU</th>
                <th>竞品数</th>
                <th>价格区间</th>
                <th>最高月销</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g, i) => {
                const prices = g.competitors.map((c) => c.price)
                const minP = Math.min(...prices)
                const maxP = Math.max(...prices)
                const maxSales = Math.max(...g.competitors.map((c) => c.sales))
                return (
                  <React.Fragment key={i}>
                    <tr style={{ cursor: 'pointer' }} onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}>
                      <td>{g.match_sku}</td>
                      <td className="tabular">{g.competitors.length}</td>
                      <td className="tabular">{minP}-{maxP}</td>
                      <td className="tabular">{maxSales.toLocaleString()}</td>
                      <td><button className="btn-sm btn-reject" onClick={(e) => { e.stopPropagation(); handleDeleteGroup(i) }}>删除</button></td>
                    </tr>
                    {expandedIdx === i && g.competitors.map((c, j) => (
                      <tr key={`${i}-${j}`} style={{ background: 'var(--bg-secondary, #f8f9fa)' }}>
                        <td style={{ paddingLeft: '2rem' }}>{c.title}</td>
                        <td className="tabular">{c.price}</td>
                        <td></td>
                        <td className="tabular">{c.sales.toLocaleString()}</td>
                        <td><button className="btn-sm btn-reject" onClick={() => handleDeleteProduct(i, j)}>删除</button></td>
                      </tr>
                    ))}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {groups.length === 0 && !showAdd && (
        <div className="erp-empty">
          <p>暂无竞品数据。支持导入 JSON 或 CSV 文件，也可手动逐条添加。</p>
          <p className="muted">JSON 格式：[{`{match_sku, competitors: [{title, price, sales}]}`}]</p>
          <p className="muted">每组通过 SKU ID 对标一个我方商品，包含多条竞品的价格和销量，用于计算甜点价格。</p>
        </div>
      )}
    </div>
  )
}

function parseCsv(text: string): CompetitorGroup[] {
  const lines = text.trim().split('\n')
  if (lines.length < 2) return []
  const headers = lines[0].split(',').map((h) => h.trim())
  const grouped: Record<string, CompetitorProduct[]> = {}
  lines.slice(1).forEach((line) => {
    const vals = line.split(',').map((v) => v.trim())
    const get = (key: string) => vals[headers.indexOf(key)] || ''
    const matchSku = get('match_sku')
    if (!matchSku) return
    const product: CompetitorProduct = {
      title: get('title'),
      price: Number(get('price')) || 0,
      sales: Number(get('sales')) || 0,
    }
    if (!grouped[matchSku]) grouped[matchSku] = []
    grouped[matchSku].push(product)
  })
  return Object.entries(grouped).map(([match_sku, competitors]) => ({ match_sku, competitors }))
}
