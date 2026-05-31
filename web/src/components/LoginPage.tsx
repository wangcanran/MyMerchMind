import { useEffect, useState } from 'react'
import { fetchHealth, login, register } from '../api/client'
import './LoginPage.css'

interface LoginPageProps {
  onLoginSuccess: (username: string) => void
}

type ApiStatus = 'checking' | 'online' | 'offline'

const statusLabel: Record<ApiStatus, string> = {
  checking: '正在探测后端服务',
  online: '后端在线，可直接登录与生成报告',
  offline: '后端未连通，先启动 API 再登录',
}

export function LoginPage({ onLoginSuccess }: LoginPageProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [isRegistering, setIsRegistering] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')

  useEffect(() => {
    let cancelled = false

    void (async () => {
      try {
        await fetchHealth()
        if (!cancelled) {
          setApiStatus('online')
        }
      } catch {
        if (!cancelled) {
          setApiStatus('offline')
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [])

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSuccess(null)
    setIsSubmitting(true)

    try {
      const cleanUsername = username.trim()
      if (isRegistering) {
        const data = await register(cleanUsername, password)
        setSuccess(data.message || '注册成功，请使用新账号登录。')
        setIsRegistering(false)
        setPassword('')
      } else {
        await login(cleanUsername, password)
        onLoginSuccess(cleanUsername)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '认证失败')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="login-shell">
      <section className="login-hero">
        <div className="login-badge">AI-Powered Commerce</div>
        <h1>
          <span className="brand-name">MerchMind</span>
          <span className="brand-tagline">数据驱动的商品决策平台</span>
        </h1>
        <p className="login-hero-copy">
          多源数据洞察 · 趋势预判 · 智能定价 · 经验沉淀 · 全链路策略追踪
        </p>
        <div className="login-status-strip">
          <span className={`status-dot status-dot--${apiStatus}`} />
          <span>{statusLabel[apiStatus]}</span>
        </div>
        <div className="login-highlights">
          <article>
            <span className="highlight-icon">01</span>
            <strong>趋势感知引擎</strong>
            <p>多维数据交叉分析，捕捉品类增长信号</p>
          </article>
          <article>
            <span className="highlight-icon">02</span>
            <strong>动态定价模型</strong>
            <p>竞品基准 × 毛利约束 × 渠道弹性，输出价格矩阵</p>
          </article>
          <article>
            <span className="highlight-icon">03</span>
            <strong>策略闭环追踪</strong>
            <p>从决策到执行到复盘，全流程数据沉淀</p>
          </article>
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-card">
          <div className="auth-card-head">
            <p className="eyebrow">{isRegistering ? 'Create Access' : 'Secure Sign-In'}</p>
            <h2>{isRegistering ? '注册账号' : '登录看板'}</h2>
            <p>
              {isRegistering
                ? '创建一个运营账号，后续用它查看策略和下载报告。'
                : '登录后自动进入今日选品与定价工作台。'}
            </p>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            <label className="auth-field" htmlFor="username">
              用户名
              <input
                id="username"
                type="text"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="例如 merch_ops"
                required
              />
            </label>
            <label className="auth-field" htmlFor="password">
              密码
              <input
                id="password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="请输入密码"
                required
              />
            </label>

            {success && <p className="auth-message auth-message--success">{success}</p>}
            {error && <p className="auth-message auth-message--error">{error}</p>}

            <button
              type="submit"
              className="auth-submit"
              disabled={isSubmitting || apiStatus === 'checking'}
            >
              {isSubmitting
                ? '处理中...'
                : isRegistering
                  ? '完成注册'
                  : '进入策略工作台'}
            </button>
          </form>

          <div className="auth-footer">
            <button
              type="button"
              className="auth-toggle"
              onClick={() => {
                setIsRegistering((value) => !value)
                setError(null)
                setSuccess(null)
              }}
            >
              {isRegistering ? '已有账号，去登录' : '没有账号，先注册'}
            </button>
            <p>密码加密存储 · 接口权限校验</p>
          </div>
        </div>
      </section>
    </div>
  )
}
