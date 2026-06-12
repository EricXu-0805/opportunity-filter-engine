'use client';

/*
 * Labs prototype — the auth card for the redesigned sign-in page.
 *
 * Visual idiom: page-surface card (Card.tsx: bg-white rounded-3xl
 * shadow-[0_2px_12px_rgba(0,0,0,0.06)]), AuthModal input + CTA classes,
 * SaveSearchDialog's gray-50/80 inset-box for the detection chip.
 *
 * Nothing here talks to Supabase: the Google button is a disabled
 * visual with a "design preview" tooltip, and "Send magic link" flips
 * to a mocked sent panel. Strings are plain bilingual on purpose —
 * production moves them into the i18n dictionaries.
 */

import { CheckCircle, GraduationCap, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { detectSchool } from './schools';

function GoogleLogo() {
  return (
    <svg viewBox="0 0 24 24" className="w-[18px] h-[18px] shrink-0" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47a5.57 5.57 0 0 1-2.4 3.58v3h3.86c2.26-2.09 3.56-5.17 3.56-8.82z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09A11.99 11.99 0 0 0 12 24z"
      />
      <path
        fill="#FBBC05"
        d="M5.27 14.29A7.13 7.13 0 0 1 4.89 12c0-.8.14-1.57.38-2.29V6.62H1.29a11.97 11.97 0 0 0 0 10.76l3.98-3.09z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42A11.97 11.97 0 0 0 1.29 6.62l3.98 3.09C6.22 6.86 8.87 4.75 12 4.75z"
      />
    </svg>
  );
}

export default function AuthCard() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const detection = detectSchool(email);

  if (sent) {
    return (
      <div className="bg-white rounded-3xl shadow-[0_2px_12px_rgba(0,0,0,0.06)] p-8 animate-in">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center shrink-0">
            <CheckCircle className="w-5 h-5 text-emerald-600" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="text-[16px] font-semibold text-gray-900">Check your inbox</h2>
            <p className="text-[12px] text-gray-500 truncate">
              登录链接已发送到 {email.trim().toLowerCase()}
            </p>
          </div>
        </div>

        <div className="bg-gray-50 border border-gray-100 rounded-xl px-4 py-3 mt-4">
          <p className="text-[13px] text-gray-700 leading-relaxed">
            Open the link in this browser to finish signing in.
            请在当前这个浏览器打开链接，完成登录。
          </p>
        </div>

        <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2 mt-3">
          <ShieldCheck className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" aria-hidden="true" />
          <p className="text-[11px] text-amber-900 leading-relaxed">
            Design preview — no email was actually sent. 设计稿预览：没有真的发送邮件。
          </p>
        </div>

        <div className="flex justify-end mt-4">
          <button
            type="button"
            onClick={() => setSent(false)}
            className="px-4 py-1.5 text-[13px] font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
          >
            Back · 返回
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-3xl shadow-[0_2px_12px_rgba(0,0,0,0.06)] p-8">
      <h2 className="text-[17px] font-semibold text-gray-900">Sign in to OpportunityEngine</h2>
      <p className="text-[12px] text-gray-500 mt-1 leading-relaxed">
        One tap with Google, or a magic link by email — no password, ever.
      </p>
      <p className="text-[12px] text-gray-400 leading-relaxed">
        Google 一键登录，或邮箱链接登录，无需密码。
      </p>

      <div className="relative group mt-6">
        <button
          type="button"
          disabled
          aria-describedby="google-preview-tip"
          className="w-full flex items-center justify-center gap-2.5 py-2.5 rounded-xl border border-gray-200 bg-white text-[14px] font-medium text-gray-700 cursor-not-allowed"
        >
          <GoogleLogo />
          Continue with Google
        </button>
        <span
          id="google-preview-tip"
          role="tooltip"
          className="pointer-events-none absolute -top-9 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-lg bg-gray-900 px-2.5 py-1.5 text-[11px] text-white opacity-0 transition-opacity group-hover:opacity-100"
        >
          Design preview — not wired up yet · 预览版，暂未接通
        </span>
      </div>

      <div className="flex items-center gap-3 my-5" aria-hidden="true">
        <span className="h-px flex-1 bg-gray-200" />
        <span className="text-[11px] text-gray-400">or · 或</span>
        <span className="h-px flex-1 bg-gray-200" />
      </div>

      <form
        onSubmit={e => {
          e.preventDefault();
          setSent(true);
        }}
        className="space-y-3"
      >
        <label className="block">
          <span className="text-[12px] font-medium text-gray-700">Email · 邮箱</span>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="you@illinois.edu"
            className="mt-1.5 w-full px-3.5 py-2.5 border border-gray-200 rounded-xl text-[14px] focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none"
          />
        </label>

        {/* The centerpiece: live .edu detection chip. Keyed by school id
            so switching domains re-runs the fade-slide-in animation. */}
        {detection.kind === 'school' && (
          <div
            key={detection.school.id}
            data-testid="school-chip"
            className="animate-in flex items-start gap-2.5 rounded-xl border border-gray-100 bg-gray-50/80 px-3 py-2.5"
          >
            <span
              className="mt-1.5 w-2.5 h-2.5 rounded-full shrink-0"
              style={{ backgroundColor: detection.school.color }}
              aria-hidden="true"
            />
            <div className="min-w-0">
              <p className="flex items-center gap-1.5 text-[13px] font-medium text-gray-800">
                <span className="truncate">{detection.school.name}</span>
                <CheckCircle className="w-3.5 h-3.5 text-emerald-600 shrink-0" aria-hidden="true" />
              </p>
              <p className="text-[11px] text-gray-500 mt-0.5">
                将自动设为你的学校 · We’ll set {detection.school.shortName} as your school
              </p>
            </div>
          </div>
        )}
        {detection.kind === 'edu' && (
          <div
            data-testid="edu-chip"
            className="animate-in flex items-start gap-2.5 rounded-xl border border-gray-100 bg-gray-50/80 px-3 py-2.5"
          >
            <GraduationCap className="w-4 h-4 text-gray-400 shrink-0 mt-0.5" aria-hidden="true" />
            <div>
              <p className="text-[13px] font-medium text-gray-700">
                Student email detected · 检测到学生邮箱
              </p>
              <p className="text-[11px] text-gray-500 mt-0.5">
                We’ll ask for your school after you sign in. 登录后再选择学校。
              </p>
            </div>
          </div>
        )}

        <button
          type="submit"
          className="w-full py-2.5 rounded-xl bg-blue-600 text-white text-[14px] font-medium hover:bg-blue-700 transition-colors"
        >
          Send magic link · 发送登录链接
        </button>

        <p className="text-[11px] text-gray-400 text-center leading-relaxed pt-1">
          One email, no password, no spam. We only use it to sign you in and sync your data.
          <br />
          只发一封登录邮件；邮箱仅用于登录与数据同步。
        </p>
      </form>
    </div>
  );
}
