import { FileText, Sparkles, Send, Shield, Github, ArrowUpRight } from 'lucide-react';

const STEPS = [
  {
    num: '01',
    icon: FileText,
    title: 'Build Your Profile',
    description:
      'Academic background, research interests, resume upload with auto skill extraction.',
  },
  {
    num: '02',
    icon: Sparkles,
    title: 'AI Matching',
    description:
      '1800+ opportunities from 6 sources, scored on eligibility, readiness, and upside with TF-IDF semantic matching.',
  },
  {
    num: '03',
    icon: Send,
    title: 'Take Action',
    description:
      'Ranked results with explanations. One-click cold emails. Clear next steps.',
  },
] as const;

const STACK = [
  { label: 'Next.js 14', category: 'Frontend' },
  { label: 'Tailwind CSS', category: 'Frontend' },
  { label: 'FastAPI', category: 'Backend' },
  { label: 'Python 3.11', category: 'Backend' },
  { label: 'Supabase', category: 'Database' },
  { label: 'Vercel', category: 'Deploy' },
  { label: 'GitHub Actions', category: 'CI/CD' },
  { label: 'scikit-learn', category: 'ML' },
] as const;

export default function AboutPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-20">

      <div className="text-center mb-20">
        <h1 className="text-5xl sm:text-6xl font-bold text-gray-900 tracking-tight leading-[1.1]">
          Connecting Students
          <br />
          <span className="bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
            with Opportunities
          </span>
        </h1>
        <p className="mt-6 text-lg text-gray-400 leading-relaxed max-w-xl mx-auto">
          An AI-powered tool that helps UIUC undergraduates discover
          research and internships that actually match their background.
        </p>
      </div>

      <div className="mb-20">
        <h2 className="text-[13px] font-semibold text-gray-400 uppercase tracking-widest text-center mb-12">
          How it works
        </h2>
        <div className="space-y-0">
          {STEPS.map((step, i) => (
            <div
              key={step.title}
              className={`flex items-start gap-8 py-10 ${i < STEPS.length - 1 ? 'border-b border-black/[0.04]' : ''}`}
            >
              <div className="shrink-0 w-12">
                <span className="text-3xl font-bold text-gray-200 tabular-nums">{step.num}</span>
              </div>
              <div>
                <div className="flex items-center gap-3 mb-2">
                  <step.icon className="w-5 h-5 text-blue-500" />
                  <h3 className="text-[17px] font-semibold text-gray-900">{step.title}</h3>
                </div>
                <p className="text-[15px] text-gray-400 leading-relaxed">
                  {step.description}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mb-20">
        <h2 className="text-[13px] font-semibold text-gray-400 uppercase tracking-widest text-center mb-12">
          Built with
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
            <h3 className="text-[15px] font-semibold text-gray-900 mb-1.5">Privacy</h3>
            <p className="text-[14px] text-gray-400 leading-relaxed">
              Your profile and resume are processed locally in your browser and never stored permanently.
              No tracking. No data selling. Resume parsing happens client-side with pdf.js.
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
          View on GitHub
          <ArrowUpRight className="w-3 h-3" />
        </a>
      </div>

      <div className="text-center">
        <p className="text-[15px] text-gray-900 font-medium">Guoyi Xu (Eric)</p>
        <p className="text-[13px] text-gray-400 mt-1">UIUC Electrical & Computer Engineering</p>
      </div>

      <div className="mt-12 text-center">
        <p className="text-[11px] text-gray-400 leading-relaxed max-w-md mx-auto">
          Independent student project. Not affiliated with the University of Illinois.
          Opportunity data is aggregated from public sources.
        </p>
      </div>
    </div>
  );
}
