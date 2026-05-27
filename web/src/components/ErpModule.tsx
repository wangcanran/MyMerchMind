import { useState, useCallback, useEffect } from 'react'

interface SkuRecord {
  sku_id: string
  name: string
  price: number
  cost_price: number
  daily_sales: number
  stock: number
  in_transit: number
  return_rate: number
  channel_sales: { live: number; private: number; shelf: number }
  conversion_rate: number
  stock_age_days: number
}

const ERP_STORAGE_KEY = 'erp_sku_data'

function loadStoredSkus(): SkuRecord[] {
  try {
    const raw = sessionStorage.getItem(ERP_STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveSkus(skus: SkuRecord[]) {
  sessionStorage.setItem(ERP_STORAGE_KEY, JSON.stringify(skus))
}

export function ErpModule() {
  const [skus, setSkus] = useState<SkuRecord[]>(loadStoredSkus)
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState('')
  const [showAdd, setShowAdd] = useState(false)

  useEffect(() => { saveSkus(skus) }, [skus])
  const [newSku, setNewSku] = useState({
    sku_id: '', name: '', price: 0, cost_price: 0,
    daily_sales: 0, stock: 0, in_transit: 0, return_rate: 0,
    conversion_rate: 0, stock_age_days: 0,
    live: 0, private_ch: 0, shelf: 0,
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
        let data: SkuRecord[]
        if (file.name.endsWith('.csv')) {
          data = parseCsv(text)
        } else {
          const parsed = JSON.parse(text)
          data = Array.isArray(parsed) ? parsed : parsed.skus || parsed.data || []
        }
        setSkus(data)
        setMessage(`导入成功：${data.length} 条 SKU 数据`)
      } catch (err) {
        setMessage(`导入失败：${err instanceof Error ? err.message : '格式错误'}`)
      } finally {
        setUploading(false)
      }
    }
    reader.readAsText(file, 'UTF-8')
    e.target.value = ''
  }, [])

  const handleAddSku = () => {
    const record: SkuRecord = {
      sku_id: newSku.sku_id,
      name: newSku.name,
      price: newSku.price,
      cost_price: newSku.cost_price,
      daily_sales: newSku.daily_sales,
      stock: newSku.stock,
      in_transit: newSku.in_transit,
      return_rate: newSku.return_rate / 100,
      conversion_rate: newSku.conversion_rate / 100,
      stock_age_days: newSku.stock_age_days,
      channel_sales: { live: newSku.live, private: newSku.private_ch, shelf: newSku.shelf },
    }
    setSkus((prev) => [...prev, record])
    setNewSku({ sku_id: '', name: '', price: 0, cost_price: 0, daily_sales: 0, stock: 0, in_transit: 0, return_rate: 0, conversion_rate: 0, stock_age_days: 0, live: 0, private_ch: 0, shelf: 0 })
    setShowAdd(false)
    setMessage('已添加 1 条 SKU')
  }

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(skus, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'erp_data.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleDelete = (id: string) => {
    setSkus((prev) => prev.filter((s) => s.sku_id !== id))
  }

  return (
    <div className="erp-module">
      <div className="erp-module__header">
        <h2>ERP 数据管理</h2>
        <div className="erp-module__actions">
          <label className="btn btn-sm btn-feedback" style={{ cursor: 'pointer' }}>
            {uploading ? '导入中...' : '导入 JSON/CSV'}
            <input type="file" accept=".json,.csv" onChange={handleFileUpload} style={{ display: 'none' }} />
          </label>
          <button className="btn btn-sm btn-accept" onClick={() => setShowAdd(!showAdd)}>
            {showAdd ? '取消' : '手动添加'}
          </button>
          {skus.length > 0 && (
            <button className="btn btn-sm btn-reject" onClick={handleExport}>导出 JSON</button>
          )}
        </div>
      </div>

      {message && <p className="erp-message">{message}</p>}

      {showAdd && (
        <div className="erp-add-form">
          <div className="erp-form-grid">
            <div className="form-group">
              <label>SKU 编号</label>
              <input type="text" placeholder="SKU1001" value={newSku.sku_id} onChange={(e) => setNewSku({ ...newSku, sku_id: e.target.value })} />
            </div>
            <div className="form-group">
              <label>商品名称</label>
              <input type="text" placeholder="黑色连衣裙" value={newSku.name} onChange={(e) => setNewSku({ ...newSku, name: e.target.value })} />
            </div>
            <div className="form-group">
              <label>售价 (元)</label>
              <input type="number" value={newSku.price || ''} onChange={(e) => setNewSku({ ...newSku, price: Number(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>成本价 (元)</label>
              <input type="number" value={newSku.cost_price || ''} onChange={(e) => setNewSku({ ...newSku, cost_price: Number(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>日均销量</label>
              <input type="number" value={newSku.daily_sales || ''} onChange={(e) => setNewSku({ ...newSku, daily_sales: Number(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>当前库存</label>
              <input type="number" value={newSku.stock || ''} onChange={(e) => setNewSku({ ...newSku, stock: Number(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>在途库存</label>
              <input type="number" value={newSku.in_transit || ''} onChange={(e) => setNewSku({ ...newSku, in_transit: Number(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>退货率 (%)</label>
              <input type="number" step="0.1" value={newSku.return_rate || ''} onChange={(e) => setNewSku({ ...newSku, return_rate: Number(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>转化率 (%)</label>
              <input type="number" step="0.1" value={newSku.conversion_rate || ''} onChange={(e) => setNewSku({ ...newSku, conversion_rate: Number(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>库龄 (天)</label>
              <input type="number" value={newSku.stock_age_days || ''} onChange={(e) => setNewSku({ ...newSku, stock_age_days: Number(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>直播销量</label>
              <input type="number" value={newSku.live || ''} onChange={(e) => setNewSku({ ...newSku, live: Number(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>私域销量</label>
              <input type="number" value={newSku.private_ch || ''} onChange={(e) => setNewSku({ ...newSku, private_ch: Number(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>货架销量</label>
              <input type="number" value={newSku.shelf || ''} onChange={(e) => setNewSku({ ...newSku, shelf: Number(e.target.value) })} />
            </div>
          </div>
          <button className="btn btn-primary" disabled={!newSku.sku_id || !newSku.name} onClick={handleAddSku}>
            添加 SKU
          </button>
        </div>
      )}

      {skus.length > 0 && (
        <div className="erp-table-wrap">
          <table className="erp-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>名称</th>
                <th>售价</th>
                <th>成本</th>
                <th>日销</th>
                <th>库存</th>
                <th>在途</th>
                <th>退货率</th>
                <th>转化率</th>
                <th>库龄</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {skus.map((s) => (
                <tr key={s.sku_id}>
                  <td className="tabular">{s.sku_id}</td>
                  <td>{s.name}</td>
                  <td className="tabular">{s.price}</td>
                  <td className="tabular">{s.cost_price}</td>
                  <td className="tabular">{s.daily_sales}</td>
                  <td className="tabular">{s.stock}</td>
                  <td className="tabular">{s.in_transit}</td>
                  <td className="tabular">{(s.return_rate * 100).toFixed(1)}%</td>
                  <td className="tabular">{(s.conversion_rate * 100).toFixed(2)}%</td>
                  <td className="tabular">{s.stock_age_days}d</td>
                  <td><button className="btn-sm btn-reject" onClick={() => handleDelete(s.sku_id)}>删除</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {skus.length === 0 && !showAdd && (
        <div className="erp-empty">
          <p>暂无 ERP 数据。支持导入 JSON 或 CSV 文件，也可手动逐条添加。</p>
          <p className="muted">JSON 格式：数组，每项包含 sku_id, name, price, cost_price, daily_sales, stock, in_transit, return_rate, channel_sales, conversion_rate, stock_age_days</p>
        </div>
      )}
    </div>
  )
}

function parseCsv(text: string): SkuRecord[] {
  const lines = text.trim().split('\n')
  if (lines.length < 2) return []
  const headers = lines[0].split(',').map((h) => h.trim())
  return lines.slice(1).map((line) => {
    const vals = line.split(',').map((v) => v.trim())
    const get = (key: string) => vals[headers.indexOf(key)] || ''
    return {
      sku_id: get('sku_id'),
      name: get('name'),
      price: Number(get('price')) || 0,
      cost_price: Number(get('cost_price')) || 0,
      daily_sales: Number(get('daily_sales')) || 0,
      stock: Number(get('stock')) || 0,
      in_transit: Number(get('in_transit')) || 0,
      return_rate: Number(get('return_rate')) || 0,
      conversion_rate: Number(get('conversion_rate')) || 0,
      stock_age_days: Number(get('stock_age_days')) || 0,
      channel_sales: {
        live: Number(get('live') || get('channel_live')) || 0,
        private: Number(get('private') || get('channel_private')) || 0,
        shelf: Number(get('shelf') || get('channel_shelf')) || 0,
      },
    }
  }).filter((s) => s.sku_id)
}
