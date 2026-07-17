import { useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  User, Lock, Eye, EyeOff, LifeBuoy, X,
  FileText, Zap, ScanSearch, KeyRound, CalendarClock, Layers,
} from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';
import { cn }      from '@/lib/cn';
import { APP_COMPANY } from '@/utils/constants';
import uviraLogo from '@/assets/uvira-logo-transparent.png';

/* ─── Injected animations ─────────────────────────────────────────────────── */
const CSS = `
@keyframes fadeUp {
  from { opacity:0; transform:translateY(16px); }
  to   { opacity:1; transform:translateY(0); }
}
@keyframes fadeIn {
  from { opacity:0; }
  to   { opacity:1; }
}
@keyframes glowPulse {
  0%,100% { box-shadow: 0 0 0 0 rgba(99,102,241,0.35); }
  50%      { box-shadow: 0 0 0 9px rgba(99,102,241,0); }
}
@keyframes shimBtn {
  0%   { transform:translateX(-120%); }
  100% { transform:translateX(200%); }
}
`;

/* ─── Structured feature timeline — what the platform actually does ─────────── */
const FEATURES = [
  { icon: FileText,     title: 'Automated Invoice Capture', desc: 'Vendor, PO, GSTIN, and line items lifted straight off the document.' },
  { icon: ScanSearch,   title: '45+ Fields at 99.9% Accuracy', desc: 'Our OCR engine extracts every field with production-grade precision.' },
  { icon: Zap,          title: 'Direct SAP Integration', desc: 'Pre-built connectors post straight into MIRO, MIGO, FB60, and F-26.' },
  { icon: Layers,       title: '5 Core Processes, Automated', desc: 'One platform spans invoicing, GRN, payments, and sales orders end to end.' },
  { icon: KeyRound,     title: 'Role-Based Access', desc: 'Admins, managers, and operators each see exactly what they need.' },
  { icon: CalendarClock,title: 'Complete Audit Trail', desc: 'Every login, upload, and posting is logged with user and timestamp.' },
];

export default function LoginPage() {
  const { login } = useAuth();
  const navigate  = useNavigate();
  const [params]  = useSearchParams();
  const returnTo  = params.get('returnTo') ?? '/dashboard';

  const [email,        setEmail]        = useState('');
  const [password,     setPassword]     = useState('');
  const [showPass,     setShowPass]     = useState(false);
  const [error,        setError]        = useState('');
  const [isPending,    setIsPending]    = useState(false);
  const [showSupport,  setShowSupport]  = useState(false);

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
    <>
      <style>{CSS}</style>

      <div
        className="relative min-h-dvh md:h-dvh w-full grid grid-cols-1 md:grid-cols-[1fr_1.05fr] md:overflow-hidden"
        style={{
          background: 'linear-gradient(112deg, #f7f2e7 0%, #f4ecdf 22%, #ddd6e8 40%, #9d94c8 52%, #4c3f8f 64%, #221756 78%, #0f1130 100%)',
        }}
      >

        {/* ══ LEFT — member login form ══════════════════════════════════ */}
        <div className="relative flex flex-col px-6 py-10 sm:px-12 md:h-full md:overflow-y-auto lg:px-20 xl:px-24">
          <div className="w-full max-w-sm mx-auto relative z-10 my-auto py-4" style={{ animation: 'fadeUp 0.5s ease-out both' }}>

            {/* Logo — leading brand element, sized to command the panel */}
            <img
              src={uviraLogo}
              alt="Uvira.ai"
              className="h-28 lg:h-32 xl:h-40 w-auto max-w-[85%] object-contain object-left mb-5 lg:mb-6 -ml-3"
            />

            {/* Heading */}
            <h1 className="text-3xl font-extrabold text-[#0f1130] tracking-tight">
              Member Login
            </h1>
            <p className="mt-1.5 text-sm text-slate-500">
              Brought to you by Sage Technology
            </p>

            {/* Form */}
            <form onSubmit={handleSubmit} className="mt-8 space-y-4">

              {/* Email */}
              <div className="relative">
                <User className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 h-4.5 w-4.5 text-slate-400" />
                <input
                  id="email" type="email" value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="User ID / Email"
                  autoComplete="email" autoFocus required disabled={isPending}
                  className={cn(
                    'block w-full rounded-full border border-slate-200 bg-white px-11 py-3.5 text-[14px] shadow-sm',
                    'text-slate-900 placeholder:text-slate-400',
                    'focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100',
                    'disabled:cursor-not-allowed disabled:opacity-60 transition-all duration-200',
                  )}
                />
              </div>

              {/* Password */}
              <div className="relative">
                <Lock className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 h-4.5 w-4.5 text-slate-400" />
                <input
                  id="password" type={showPass ? 'text' : 'password'} value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="Password"
                  autoComplete="current-password" required disabled={isPending}
                  className={cn(
                    'block w-full rounded-full border border-slate-200 bg-white px-11 py-3.5 pr-11 text-[14px] shadow-sm',
                    'text-slate-900 placeholder:text-slate-400',
                    'focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100',
                    'disabled:cursor-not-allowed disabled:opacity-60 transition-all duration-200',
                  )}
                />
                <button type="button" tabIndex={-1}
                  onClick={() => setShowPass(v => !v)}
                  className="absolute inset-y-0 right-0 flex items-center px-4 text-slate-400 hover:text-slate-600 transition-colors"
                  aria-label={showPass ? 'Hide' : 'Show'}>
                  {showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>

              {/* Error */}
              {error && (
                <div className="flex items-center gap-2 rounded-xl bg-red-50 px-4 py-2.5 text-[13px] text-red-700 ring-1 ring-red-200">
                  <span className="shrink-0">⚠</span>
                  <span>{error}</span>
                </div>
              )}

              {/* Sign in button */}
              <button
                type="submit"
                disabled={isPending || !email || !password}
                className="relative w-full overflow-hidden rounded-full py-3.5 text-[15px] font-semibold text-white transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 mt-2"
                style={{ background: 'linear-gradient(90deg,#4f46e5 0%,#0ea5e9 100%)' }}
              >
                {isPending ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Signing in…
                  </span>
                ) : 'Sign In to UVIRA'}
                <span className="pointer-events-none absolute inset-0 -translate-x-full skew-x-[-20deg] bg-white/20 w-1/2"
                      style={{ animation: 'shimBtn 2.5s ease-in-out infinite' }} />
              </button>
            </form>

            {/* Forgot password */}
            <div className="mt-5 text-center">
              <button
                type="button"
                onClick={() => setShowSupport(true)}
                className="text-[13px] text-slate-500 underline hover:text-indigo-600 transition-colors"
              >
                Forgot Password?
              </button>
            </div>
          </div>

          {/* Support modal */}
          {showSupport && (
            <div
              className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4"
              style={{ animation: 'fadeIn 0.15s ease-out both' }}
              onClick={() => setShowSupport(false)}
            >
              <div
                className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl"
                style={{ animation: 'fadeUp 0.25s ease-out both' }}
                onClick={e => e.stopPropagation()}
              >
                <div className="flex items-start justify-between">
                  <div className="flex h-11 w-11 items-center justify-center rounded-full bg-indigo-50">
                    <LifeBuoy className="h-5 w-5 text-indigo-600" />
                  </div>
                  <button onClick={() => setShowSupport(false)} className="text-slate-400 hover:text-slate-600">
                    <X className="h-4.5 w-4.5" />
                  </button>
                </div>
                <h3 className="mt-4 text-[16px] font-bold text-slate-900">Need help signing in?</h3>
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-slate-500">
                  Passwords for UVIRA.ai are managed by your administrator. Please contact our support team
                  and we'll get you back into your account.
                </p>
                <button
                  type="button"
                  onClick={() => setShowSupport(false)}
                  className="mt-5 w-full rounded-xl py-2.5 text-[14px] font-semibold text-white transition-all"
                  style={{ background: 'linear-gradient(90deg,#4f46e5 0%,#0ea5e9 100%)' }}
                >
                  Got it
                </button>
              </div>
            </div>
          )}
        </div>

        {/* ══ RIGHT — product showcase, shares the page-wide gradient ═════ */}
        <div className="hidden md:flex flex-col relative overflow-hidden md:h-full md:overflow-y-auto px-8 py-8 lg:px-11 lg:py-10 xl:px-14 xl:py-14">
          {/* Subtle dot grid */}
          <div className="pointer-events-none absolute inset-0 opacity-[0.05]"
               style={{ backgroundImage: 'radial-gradient(circle, #fff 1px, transparent 1px)', backgroundSize: '22px 22px' }} />
          <div className="pointer-events-none absolute top-0 right-0 h-72 w-72 rounded-full opacity-20"
               style={{ background: 'radial-gradient(circle, #6366f1, transparent 70%)' }} />
          <div className="pointer-events-none absolute bottom-0 left-0 h-56 w-56 rounded-full opacity-15"
               style={{ background: 'radial-gradient(circle, #06b6d4, transparent 70%)' }} />

          <div className="relative z-10 flex flex-col my-auto max-w-md mx-auto w-full py-6">

            {/* Overline */}
            <div className="flex items-center gap-2 mb-3 lg:mb-4" style={{ animation: 'fadeUp 0.5s ease-out 0.05s both' }}>
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shrink-0" />
              <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-emerald-400/80">
                SAP Intelligence Platform
              </span>
            </div>

            {/* Heading + supporting copy */}
            <h2 className="text-[1.45rem] lg:text-[1.6rem] xl:text-[1.75rem] font-bold leading-[1.25] text-white"
                style={{ animation: 'fadeUp 0.5s ease-out 0.1s both' }}>
              Experience Intelligent<br />SAP AP Automation.
            </h2>
            <p className="mt-3 text-[12.5px] lg:text-[13px] leading-relaxed text-white"
               style={{ animation: 'fadeUp 0.5s ease-out 0.15s both' }}>
              Our OCR engine reads 45+ data fields per document at 99.9% accuracy, feeding pre-built
              SAP integrations across 5 core financial processes — from invoice to payment, fully automated.
            </p>

            {/* Stat strip */}
            <div className="mt-5 lg:mt-6 grid grid-cols-3 gap-2.5 lg:gap-3" style={{ animation: 'fadeUp 0.5s ease-out 0.2s both' }}>
              {[
                { value: '45+',   label: 'Fields Extracted' },
                { value: '99.9%', label: 'OCR Accuracy' },
                { value: '5',     label: 'SAP Processes' },
              ].map(s => (
                <div key={s.label} className="rounded-xl border border-white/10 bg-white/[0.04] px-2.5 py-2.5 lg:px-3 lg:py-3 text-center backdrop-blur-sm">
                  <p className="text-[15px] lg:text-[17px] font-extrabold text-white leading-none"
                     style={{ backgroundImage: 'linear-gradient(90deg,#a5b4fc,#67e8f9)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                    {s.value}
                  </p>
                  <p className="mt-1.5 text-[9px] lg:text-[9.5px] font-medium uppercase tracking-wide text-slate-300 leading-tight">
                    {s.label}
                  </p>
                </div>
              ))}
            </div>

            {/* Divider */}
            <div className="my-5 lg:my-6 border-t border-white/8" />

            {/* Structured feature timeline */}
            <div className="relative">
              {/* Connecting line */}
              <div className="absolute left-[19px] top-2 bottom-2 w-px"
                   style={{ background: 'linear-gradient(180deg, rgba(99,102,241,0.5), rgba(6,182,212,0.5))' }} />

              <div className="space-y-3.5 lg:space-y-4 xl:space-y-5">
                {FEATURES.map(({ icon: Icon, title, desc }, i) => (
                  <div
                    key={title}
                    className="relative flex items-start gap-3.5"
                    style={{ animation: `fadeUp 0.45s ease-out ${0.25 + i * 0.06}s both` }}
                  >
                    <div
                      className="relative z-10 h-9 w-9 lg:h-10 lg:w-10 shrink-0 rounded-full flex items-center justify-center border border-white/10"
                      style={{ background: '#171a42', animation: 'glowPulse 3.4s ease-in-out infinite' }}
                    >
                      <Icon className="h-4 w-4 lg:h-4.5 lg:w-4.5 text-indigo-300" />
                    </div>
                    <div className="pt-1 lg:pt-1.5">
                      <p className="text-[12.5px] lg:text-[13px] font-semibold text-white leading-snug">{title}</p>
                      <p className="text-[11px] lg:text-[11.5px] text-slate-300 leading-snug mt-0.5">{desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Footer */}
            <p className="mt-6 lg:mt-8 text-[10px] text-slate-500 pt-4 border-t border-white/5">
              {APP_COMPANY}
            </p>
          </div>
        </div>

      </div>
    </>
  );
}
