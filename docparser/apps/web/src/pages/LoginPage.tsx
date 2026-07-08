import { useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Eye, EyeOff, Lock } from 'lucide-react';
import { useAuth }  from '@/hooks/useAuth';
import { Button }   from '@/components/ui/Button';
import { cn }       from '@/lib/cn';
import { APP_NAME, APP_VERSION, APP_COMPANY } from '@/utils/constants';

export default function LoginPage() {
  const { login }  = useAuth();
  const navigate   = useNavigate();
  const [params]   = useSearchParams();
  const returnTo   = params.get('returnTo') ?? '/dashboard';

  const [email,      setEmail]      = useState('');
  const [password,   setPassword]   = useState('');
  const [showPass,   setShowPass]   = useState(false);
  const [error,      setError]      = useState('');
  const [isPending,  setIsPending]  = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setIsPending(true);
    try {
      await login({ email, password });
      navigate(returnTo, { replace: true });
    } catch {
      setError('Invalid email or password. Please try again.');
    } finally {
      setIsPending(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-neutral-50 dark:bg-neutral-950 p-4">
      <div className="w-full max-w-sm">

        {/* Logo */}
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-neutral-900 dark:bg-neutral-700 shadow-lg">
            <Lock className="h-7 w-7 text-white" strokeWidth={1.75} />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-neutral-900 dark:text-neutral-100"
                style={{ fontFamily: 'var(--ff-display)' }}>{APP_NAME}</h1>
            <p className="mt-0.5 text-xs font-medium uppercase tracking-widest text-neutral-400">
              SAP Integration Suite
            </p>
          </div>
        </div>

        {/* Card */}
        <div className="rounded-2xl bg-white p-8 shadow-soft ring-1 ring-neutral-200/60 dark:bg-neutral-800 dark:ring-neutral-700/60">
          <div className="mb-6">
            <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100"
                style={{ fontFamily: 'var(--ff-display)' }}>Welcome back</h2>
            <p className="mt-0.5 text-sm text-neutral-400">
              Sign in to access the document processing portal
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email */}
            <div className="space-y-1.5">
              <label htmlFor="email" className="block text-sm font-medium text-neutral-700 dark:text-neutral-300">
                Work email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                autoComplete="email"
                autoFocus
                required
                disabled={isPending}
                className={cn(
                  'block w-full rounded-lg border border-neutral-200 bg-white px-3.5 py-2.5 text-sm',
                  'text-neutral-900 placeholder:text-neutral-400',
                  'focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-200',
                  'disabled:cursor-not-allowed disabled:bg-neutral-50 disabled:text-neutral-500',
                  'dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100 dark:placeholder:text-neutral-600',
                  'transition-colors',
                )}
              />
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <label htmlFor="password" className="block text-sm font-medium text-neutral-700 dark:text-neutral-300">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPass ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                  disabled={isPending}
                  className={cn(
                    'block w-full rounded-lg border border-neutral-200 bg-white px-3.5 py-2.5 pr-10 text-sm',
                    'text-neutral-900 placeholder:text-neutral-400',
                    'focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-200',
                    'disabled:cursor-not-allowed disabled:bg-neutral-50 disabled:text-neutral-500',
                    'dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100 dark:placeholder:text-neutral-600',
                    'transition-colors',
                  )}
                />
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={() => setShowPass((v) => !v)}
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-neutral-400 hover:text-neutral-600 transition-colors"
                  aria-label={showPass ? 'Hide password' : 'Show password'}
                >
                  {showPass
                    ? <EyeOff className="h-4 w-4" />
                    : <Eye    className="h-4 w-4" />
                  }
                </button>
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="flex items-start gap-2 rounded-lg bg-danger-50 px-3 py-2.5 text-sm text-danger-700 ring-1 ring-danger-200">
                <span className="mt-px shrink-0">⚠</span>
                <span>{error}</span>
              </div>
            )}

            <Button
              type="submit"
              className="w-full"
              loading={isPending}
              disabled={isPending || !email || !password}
            >
              {isPending ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>
        </div>

        {/* Footer */}
        <p className="mt-6 text-center text-xs text-neutral-400">
          {APP_NAME} v{APP_VERSION} &middot; {APP_COMPANY}
        </p>
      </div>
    </div>
  );
}
