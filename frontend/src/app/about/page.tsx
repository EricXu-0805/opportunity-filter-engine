import { FileText, Sparkles, Send, Shield, Github, ArrowUpRight } from 'lucide-react';
import { tServer } from '@/i18n/server';

const STEPS = [
  { num: '01', icon: FileText, titleKey: 'about.steps.buildProfile', descKey: 'about.steps.buildProfileDesc' },
  { num: '02', icon: Sparkles, titleKey: 'about.steps.aiMatching', descKey: 'about.steps.aiMatchingDesc' },
  { num: '03', icon: Send, titleKey: 'about.steps.takeAction', descKey: 'about.steps.takeActionDesc' },
] as const;

const STACK = [
  { label: 'Next.js 14', categoryKey: 'about.stackCategories.frontend' },
  { label: 'Tailwind CSS', categoryKey: 'about.stackCategories.frontend' },
  { label: 'FastAPI', categoryKey: 'about.stackCategories.backend' },
  { label: 'Python 3.11', categoryKey: 'about.stackCategories.backend' },
  { label: 'Supabase', categoryKey: 'about.stackCategories.database' },
  { label: 'Vercel', categoryKey: 'about.stackCategories.deploy' },
  { label: 'GitHub Actions', categoryKey: 'about.stackCategories.cicd' },
  { label: 'scikit-learn', categoryKey: 'about.stackCategories.ml' },
] as const;

export default function AboutPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-20">

      <div className="text-center mb-20">
        <h1 className="text-5xl sm:text-6xl font-bold text-gray-900 tracking-tight leading-[1.1]">
          {tServer('about.heroLine1')}
          <br />
          <span className="bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
            {tServer('about.heroLine2')}
          </span>
        </h1>
        <p className="mt-6 text-lg text-gray-400 leading-relaxed max-w-xl mx-auto">
          {tServer('about.heroSubtitle')}
        </p>
      </div>

      <div className="mb-20">
        <h2 className="text-[13px] font-semibold text-gray-400 uppercase tracking-widest text-center mb-12">
          {tServer('about.howItWorks')}
        </h2>
        <div className="space-y-0">
          {STEPS.map((step, i) => (
            <div
              key={step.titleKey}
              className={`flex items-start gap-8 py-10 ${i < STEPS.length - 1 ? 'border-b border-black/[0.04]' : ''}`}
            >
              <div className="shrink-0 w-12">
                <span className="text-3xl font-bold text-gray-200 tabular-nums">{step.num}</span>
              </div>
              <div>
                <div className="flex items-center gap-3 mb-2">
                  <step.icon className="w-5 h-5 text-blue-500" />
                  <h3 className="text-[17px] font-semibold text-gray-900">{tServer(step.titleKey)}</h3>
                </div>
                <p className="text-[15px] text-gray-400 leading-relaxed">
                  {tServer(step.descKey)}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mb-20">
        <h2 className="text-[13px] font-semibold text-gray-400 uppercase tracking-widest text-center mb-12">
          {tServer('about.builtWith')}
        </h2>
        <div className="flex flex-wrap justify-center gap-2">
          {STACK.map((t) => (
            <span
              key={t.label}
              className="px-4 py-2 rounded-full bg-white text-[13px] font-medium text-gray-600 shadow-[0_1px_4px_rgba(0,0,0,0.05)]"
            >
              {t.label}
            </span>
          ))}
        </div>
      </div>

      <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 mb-20">
        <div className="flex items-start gap-5">
          <div className="w-10 h-10 rounded-xl bg-blue-600/[0.08] flex items-center justify-center shrink-0">
            <Shield className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <h3 className="text-[15px] font-semibold text-gray-900 mb-1.5">{tServer('about.privacy')}</h3>
            <p className="text-[14px] text-gray-400 leading-relaxed">
              {tServer('about.privacyBody')}
            </p>
          </div>
        </div>
      </div>

      <div className="flex justify-center mb-16">
        <a
          href="https://github.com/EricXu-0805/opportunity-filter-engine"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-gray-900 text-white text-[13px] font-medium hover:bg-gray-800 transition-colors duration-300"
        >
          <Github className="w-4 h-4" />
          {tServer('about.viewOnGithub')}
          <ArrowUpRight className="w-3 h-3" />
        </a>
      </div>

      <div className="text-center">
        <p className="text-[15px] text-gray-900 font-medium">{tServer('about.author')}</p>
        <p className="text-[13px] text-gray-400 mt-1">{tServer('about.authorRole')}</p>
      </div>

      <div className="mt-12 text-center">
        <p className="text-[11px] text-gray-400 leading-relaxed max-w-md mx-auto">
          {tServer('about.disclaimer')}
        </p>
      </div>
    </div>
  );
}
