import {
  FileText,
  Sparkles,
  Send,
  Shield,
  Database,
  Cpu,
  Globe,
  Search,
  Zap,
} from 'lucide-react';
import Card from '@/components/Card';

const STEPS = [
  {
    icon: FileText,
    title: 'Build Your Profile',
    description:
      'Enter your academic background, research interests, and optionally upload your resume. Our parser extracts skills and coursework automatically.',
    color: 'bg-blue-50 text-blue-600',
  },
  {
    icon: Sparkles,
    title: 'AI Matching',
    description:
      'Our engine analyzes 58+ opportunities against your profile — scoring fit based on skills, interests, department alignment, and eligibility.',
    color: 'bg-emerald-50 text-emerald-600',
  },
  {
    icon: Send,
    title: 'Apply with Confidence',
    description:
      'Get ranked results with explanations, concerns, and next steps. Generate personalized cold emails for positions that interest you.',
    color: 'bg-amber-50 text-amber-600',
  },
] as const;

const TECH = [
  { icon: Cpu, label: 'Next.js 14', desc: 'React framework with App Router' },
  { icon: Database, label: 'FastAPI', desc: 'High-performance Python backend' },
  { icon: Sparkles, label: 'GPT-4o', desc: 'AI-powered matching & email generation' },
  { icon: Globe, label: 'Web Scraping', desc: 'Live data from UIUC research portals' },
  { icon: Search, label: 'Semantic Search', desc: 'Embedding-based opportunity ranking' },
  { icon: Zap, label: 'Real-time', desc: 'Fresh data from multiple sources' },
] as const;

export default function AboutPage() {
  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      {/* Hero */}
      <div className="text-center mb-16">
        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-blue-50 text-blue-700 text-sm font-medium mb-5">
          <Sparkles className="w-4 h-4" />
          About the Project
        </div>
        <h1 className="text-4xl sm:text-5xl font-extrabold text-gray-900 tracking-tight leading-tight">
          Connecting UIUC Students{' '}
          <br className="hidden sm:block" />
          <span className="bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
            with Opportunities
          </span>
        </h1>
        <p className="mt-5 text-lg text-gray-500 max-w-2xl mx-auto leading-relaxed">
          OpportunityEngine is an AI-powered tool that helps UIUC undergraduates
          — especially international students — discover and apply to research
          positions and internships that match their skills and interests.
        </p>
      </div>

      {/* How it works */}
      <div className="mb-16">
        <h2 className="text-2xl font-bold text-gray-900 text-center mb-10">
          How It Works
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {STEPS.map((step, i) => (
            <Card key={step.title} className="text-center relative">
              {/* Step number */}
              <div className="absolute -top-3 -left-3 w-7 h-7 rounded-full bg-gradient-to-br from-blue-600 to-blue-500 flex items-center justify-center shadow-sm">
                <span className="text-xs font-bold text-white">{i + 1}</span>
              </div>

              <div
                className={`w-14 h-14 rounded-2xl ${step.color} flex items-center justify-center mx-auto mb-5`}
              >
                <step.icon className="w-7 h-7" />
              </div>
              <h3 className="text-lg font-bold text-gray-900 mb-3">
                {step.title}
              </h3>
              <p className="text-sm text-gray-500 leading-relaxed">
                {step.description}
              </p>
            </Card>
          ))}
        </div>
      </div>

      {/* Tech Stack */}
      <div className="mb-16">
        <h2 className="text-2xl font-bold text-gray-900 text-center mb-10">
          Built With
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {TECH.map((t) => (
            <div
              key={t.label}
              className="flex items-start gap-4 p-5 rounded-2xl border border-gray-200 bg-white hover:border-blue-200 hover:shadow-sm transition-all"
            >
              <div className="w-10 h-10 rounded-xl bg-gray-50 flex items-center justify-center shrink-0">
                <t.icon className="w-5 h-5 text-gray-600" />
              </div>
              <div>
                <p className="text-sm font-bold text-gray-900">{t.label}</p>
                <p className="text-xs text-gray-500 mt-0.5">{t.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Privacy */}
      <Card className="bg-gradient-to-br from-gray-50 to-white border-gray-200">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-2xl bg-blue-50 flex items-center justify-center shrink-0">
            <Shield className="w-6 h-6 text-blue-600" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-gray-900 mb-2">
              Privacy & Data
            </h3>
            <p className="text-sm text-gray-500 leading-relaxed">
              Your profile and resume data are processed in real-time and are never
              stored permanently. All matching happens server-side using your session
              data only. We don&apos;t track users or sell data.
            </p>
          </div>
        </div>
      </Card>

      {/* Disclaimer */}
      <div className="mt-12 text-center">
        <p className="text-xs text-gray-400 leading-relaxed max-w-xl mx-auto">
          OpportunityEngine is an independent student project and is not
          officially affiliated with, endorsed by, or maintained by the
          University of Illinois Urbana-Champaign. Opportunity data is
          aggregated from public sources and may not be complete or up to
          date.
        </p>
      </div>
    </div>
  );
}
