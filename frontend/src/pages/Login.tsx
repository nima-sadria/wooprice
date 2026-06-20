import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'

export default function Login() {
  const { refreshUser } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      })

      if (!r.ok) {
        const data = await r.json().catch(() => ({})) as { detail?: string }
        if (r.status === 401) {
          setError(data.detail ?? 'Invalid credentials. Please check your username and password.')
        } else if (r.status === 403) {
          setError(data.detail ?? 'Access not granted — contact your administrator.')
        } else if (r.status === 503) {
          setError('Authentication service is temporarily unavailable. Please try again.')
        } else {
          setError(data.detail ?? `Login failed (HTTP ${r.status}). Please try again.`)
        }
        return
      }

      const data = await r.json() as { token: string }
      localStorage.setItem('wp_token', data.token)
      await refreshUser()
      navigate('/home', { replace: true })
    } catch {
      setError('Network error. Please check your connection and try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-bg-base flex items-center justify-center p-4">
      <div className="w-full max-w-sm bg-bg-card border border-border rounded-card shadow-card p-8">
        <div className="mb-7 text-center">
          <h1 className="text-[22px] font-bold text-text-base">WooPrice</h1>
          <p className="text-[13px] text-wp-muted mt-1">Sign in with your Nextcloud account</p>
        </div>

        {error && (
          <div role="alert" className="mb-4 bg-[#fee2e2] border border-[#ef4444]/30 rounded-lg px-4 py-3 text-[13px] text-[#dc2626]">
            {error}
          </div>
        )}

        <form onSubmit={(e) => { void handleSubmit(e) }} className="flex flex-col gap-4">
          <div>
            <label htmlFor="login-username" className="block text-[13px] font-medium text-text-base mb-1.5">
              Username
            </label>
            <input
              id="login-username"
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
              autoComplete="username"
              autoFocus
              disabled={loading}
              className="w-full border border-border rounded-lg px-3 py-2 text-[14px] bg-bg-base text-text-base focus:outline-none focus:border-accent placeholder:text-wp-muted disabled:opacity-60"
              placeholder="Nextcloud username"
            />
          </div>

          <div>
            <label htmlFor="login-password" className="block text-[13px] font-medium text-text-base mb-1.5">
              Password
            </label>
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              disabled={loading}
              className="w-full border border-border rounded-lg px-3 py-2 text-[14px] bg-bg-base text-text-base focus:outline-none focus:border-accent placeholder:text-wp-muted disabled:opacity-60"
              placeholder="Nextcloud password"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="mt-2 w-full bg-accent text-white py-2.5 rounded-lg text-[14px] font-semibold hover:bg-accent/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
