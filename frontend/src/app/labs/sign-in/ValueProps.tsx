'use client';

/*
 * Labs prototype — promo side of the sign-in page: brand mark, headline,
 * and the three value props. Idiom sources: HeroSection (pill tagline,
 * gradient accent, tracking-tight headline), AuthModal (icon-in-rounded-
 * square chips, bracketed font sizes).
 */

import { Inbox, MonitorSmartphone, ShieldCheck, Sparkles } from 'lucide-react';

const PROPS = [
  {
    icon: MonitorSmartphone,
    en: 'Sync across all your devices',
    body: 'Your profile, favorites, and application tracker follow you — laptop, phone, library computer.',
    zh: '资料、收藏与申请追踪，在所有设备实时同步。',
    miniEn: 'Sync everywhere',
    miniZh: '全设备同步',
  },
  {
    icon: ShieldCheck,
    en: 'Never lose your work',
    body: 'Everything you saved as a guest merges into your account the moment you sign in.',
    zh: '游客模式下保存的一切，登录后自动并入账号，不会丢失。',
    miniEn: 'Never lose work',
    miniZh: '数据不丢失',
  },
  {
    icon: Inbox,
    en: 'New matches, delivered weekly',
    body: 'Saved searches keep watching 4,600+ opportunities and email you only when something new fits.',
    zh: '保存的搜索持续盯紧新机会，有合适的才发邮件提醒。',
    miniEn: 'Weekly matches',
    miniZh: '每周新匹配',
  },
] as const;

export function BrandMark({ centered = false }: { centered?: boolean }) {
  return (
    <div className={`flex items-center gap-2 ${centered ? 'justify-center' : ''}`}>
      <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-600 to-blue-500 flex items-center justify-center shrink-0">
        <Sparkles className="w-3.5 h-3.5 text-white" strokeWidth={2.5} aria-hidden="true" />
      </div>
      <span className="text-[15px] font-semibold text-gray-900 tracking-tight">
        Opportunity<span className="text-blue-600">Engine</span>
      </span>
    </div>
  );
}

export function Headline({ centered = false }: { centered?: boolean }) {
  return (
    <div className={centered ? 'text-center' : ''}>
      <BrandMark centered={centered} />
      <div className="mt-6 inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-blue-600/[0.08] text-blue-600 text-[13px] font-medium">
        <Sparkles className="w-3.5 h-3.5" aria-hidden="true" />
        Free · No password needed · 无需密码
      </div>
      <h1
        className={`mt-5 font-bold text-gray-900 tracking-tight leading-[1.1] ${
          centered ? 'text-3xl' : 'text-4xl sm:text-5xl'
        }`}
      >
        Pick up where you left off,{' '}
        <span className="bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
          anywhere
        </span>
      </h1>
      <p
        className={`mt-4 text-[15px] text-gray-500 leading-relaxed ${
          centered ? 'max-w-sm mx-auto' : 'max-w-md'
        }`}
      >
        登录后，你的资料、收藏与申请进度在手机、电脑间无缝同步。
      </p>
    </div>
  );
}

export function ValuePropList() {
  return (
    <ul className="space-y-6">
      {PROPS.map(p => (
        <li key={p.en} className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center shrink-0">
            <p.icon className="w-5 h-5 text-blue-600" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h3 className="text-[14px] font-semibold text-gray-900">{p.en}</h3>
            <p className="text-[13px] text-gray-600 leading-relaxed mt-0.5">{p.body}</p>
            <p className="text-[12px] text-gray-400 leading-relaxed mt-0.5">{p.zh}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ValuePropsRow() {
  return (
    <div className="grid grid-cols-3 gap-3">
      {PROPS.map(p => (
        <div key={p.en} className="text-center">
          <div className="w-9 h-9 rounded-xl bg-blue-50 flex items-center justify-center mx-auto">
            <p.icon className="w-[18px] h-[18px] text-blue-600" aria-hidden="true" />
          </div>
          <p className="text-[12px] font-medium text-gray-700 mt-2">{p.miniEn}</p>
          <p className="text-[11px] text-gray-400 mt-0.5">{p.miniZh}</p>
        </div>
      ))}
    </div>
  );
}
