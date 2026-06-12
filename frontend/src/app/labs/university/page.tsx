'use client';

/*
 * /labs/university — design prototype for the university switcher.
 *
 * NOT linked from any nav; direct URL only.
 *
 * DECISION (2026-06): Variant A ("全展示 + 覆盖徽章") is CHOSEN, upgraded with
 * the two-concept model — home school = identity (catalog / campus items /
 * F-1 context); discovery scope = each opportunity's own audience
 * (campus / open / unknown). Default results = home campus + all 'open'
 * items, ranked by interest fit. See ResultsScopeDemo for the post-switch
 * preview. Variant B is kept viewable for reference only (未选用).
 *
 * Strings are plain bilingual on purpose (prototype allowance);
 * production wires them through the i18n dictionaries.
 */

import { BadgeCheck, CheckCircle, FlaskConical, Landmark } from 'lucide-react';
import { useEffect, useState } from 'react';
import ResultsScopeDemo from './ResultsScopeDemo';
import UniversitySwitcherModal, { type SwitcherVariant } from './UniversitySwitcherModal';
import { findUniversity, type UniversityEntry } from './universities';

function VariantTab({ active, onClick, label, tag, tagCls }: {
  active: boolean;
  onClick: () => void;
  label: string;
  tag: string;
  tagCls: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`px-3.5 py-1.5 rounded-lg text-[13px] font-medium transition-colors ${
        active ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'
      }`}
    >
      {label}
      <span className={`ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-semibold ${tagCls}`}>{tag}</span>
    </button>
  );
}

export default function UniversityLabsPage() {
  const [variant, setVariant] = useState<SwitcherVariant>('A');
  const [currentId, setCurrentId] = useState('uiuc');
  const [modalOpen, setModalOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 2600);
    return () => window.clearTimeout(id);
  }, [toast]);

  const current = findUniversity(currentId);

  const switchVariant = (next: SwitcherVariant) => {
    setVariant(next);
    setCurrentId('uiuc');
    setModalOpen(false);
    setToast(null);
  };

  const handleVote = (entry: UniversityEntry) => {
    setToast(`已记录 · We'll notify you when ${entry.shortTag} campus data is ready`);
  };

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-16">
      <header className="mb-8">
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-amber-50/80 text-amber-600">
            <FlaskConical className="w-3 h-3" aria-hidden="true" />
            Labs · 设计原型，未接入真实数据
          </span>
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-emerald-50/80 text-emerald-600">
            <BadgeCheck className="w-3 h-3" aria-hidden="true" />
            已定稿 · Variant A + 双概念模型
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600 to-blue-500 text-white flex items-center justify-center">
            <Landmark className="w-5 h-5" aria-hidden="true" />
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 tracking-tight leading-[1.1]">
            University Switcher
          </h1>
        </div>
        <p className="mt-3 text-base text-gray-500 max-w-2xl">
          决策已定：选用方案 A，并升级为双概念模型——学校 = 身份，发现范围 = 机会自身的
          audience。点「切换学校」体验完整流程，切换后下方会出现结果页预览。方案 B 保留展示，仅作参考。
        </p>
      </header>

      <div role="tablist" aria-label="Variant" className="mb-6 flex gap-1 p-1 bg-gray-100 rounded-xl w-fit">
        <VariantTab
          active={variant === 'A'}
          onClick={() => switchVariant('A')}
          label="方案 A · 全展示 + 覆盖徽章"
          tag="已选用"
          tagCls="bg-emerald-50 text-emerald-600"
        />
        <VariantTab
          active={variant === 'B'}
          onClick={() => switchVariant('B')}
          label="方案 B · 数据优先"
          tag="未选用"
          tagCls="bg-gray-200/70 text-gray-500"
        />
      </div>

      <section className="bg-white rounded-2xl shadow-[0_2px_12px_rgba(0,0,0,0.06)] p-6 sm:p-8 mb-4">
        <p className="text-[11px] font-medium text-gray-400 uppercase tracking-wide mb-3">
          Profile · 模拟个人资料表单
        </p>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-gray-700 mb-1">你的学校 · Your university</p>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-medium bg-blue-50/80 text-blue-600">
                {current.shortTag}
              </span>
              <p className="text-[15px] font-semibold text-gray-900">{current.name}</p>
            </div>
            <p className="mt-1.5 text-[12px] text-gray-500">
              {current.catalog
                ? `${current.catalog.colleges} colleges · ${current.catalog.majors} majors（学院/专业目录驱动 Profile 表单选项）`
                : '院系目录建设中 · Profile 表单暂用自由输入'}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="shrink-0 px-4 py-2.5 rounded-xl bg-blue-600 text-white text-[13px] font-semibold hover:bg-blue-700 transition-colors"
          >
            切换学校 · Change University
          </button>
        </div>

      </section>

      {variant === 'A' && <ResultsScopeDemo key={currentId} current={current} />}

      <p className="text-[12px] text-gray-400 leading-relaxed mb-10">
        {variant === 'A'
          ? '方案 A（已选用）：所有学校都可选择，卡片上的覆盖徽章如实标注数据范围；上方结果页预览演示发现范围模型——切换不同学校（试试 UMich）观察指示行、横幅与各卡片 audience 角标的变化。'
          : '方案 B（未选用 · 仅留作参考）：只有已具备校内数据的学校（UIUC、UCB）可选；其余学校降透明度显示 Coming soon，并提供「提醒我 / Vote」按钮收集需求信号。'}
      </p>

      <section className="border-t border-gray-200 pt-8">
        <h2 className="text-sm font-semibold text-gray-900 mb-4">设计笔记 · Design notes</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <div>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-blue-50/80 text-blue-600 mb-2">
              方案 A · 全展示 + 覆盖徽章
              <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-600">✓ 已选用</span>
            </span>
            <p className="text-[12px] text-gray-500 leading-relaxed">
              任何学校都能立即选用——用户不会被挡在门外，全国性机会（NSF REU + Simplify，约 2,070 条）对所有人都有真实价值，
              覆盖徽章和切换后的结果页预览把数据边界讲清楚，符合「绝不暗示我们没有的数据」的产品文化。
            </p>
            <p className="mt-2 text-[12px] text-gray-500 leading-relaxed">
              <span className="font-medium text-gray-700">决策（2026-06）：</span>
              选用 A，并升级为双概念模型。Eric 的关键要求：想找其他学校机会的用户不应被自己的 featured/home
              school 限制——按兴趣在全部「对外开放」机会里发现。学校只决定身份（目录、校内机会、F-1
              语境）；每条机会能否被你看到由它自己的 audience（campus / open / unknown）决定。
              这也化解了 A 原本的体验落差风险：选一所暂无校内数据的学校不再是道歉式空态，
              而是「校内数据建设中——你现在就能申请的开放机会都在这里」。
            </p>
          </div>
          <div>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-indigo-50/80 text-indigo-600 mb-2">
              方案 B · 数据优先
              <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-gray-200/70 text-gray-500">未选用 · 仅留作参考</span>
            </span>
            <p className="text-[12px] text-gray-500 leading-relaxed">
              只放行数据已就绪的学校，每个可选项的体验都是完整的——预期管理最干净，不存在「选完才发现没数据」的失望路径；
              「提醒我 / Vote」把未覆盖学校变成增长信号采集器，直接告诉我们下一所该建设哪所学校的数据。代价是把全国性机会
              也一起挡住了：一个 UMich 学生本可以马上用 REU/实习数据，却被告知「敬请期待」，转化漏斗在第一步就收窄，
              并且灰色卡片墙会让目录显得「大半未完工」。落选原因即此；「提醒我 / Vote」钩子可在日后以
              「催更校内数据」的形式回到方案 A。
            </p>
          </div>
        </div>
      </section>

      {modalOpen && (
        <UniversitySwitcherModal
          variant={variant}
          initialSelectedId={currentId}
          onCancel={() => setModalOpen(false)}
          onConfirm={(id) => { setCurrentId(id); setModalOpen(false); }}
          onVote={handleVote}
        />
      )}

      {toast && (
        <div
          role="status"
          className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[70] flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gray-900 text-white text-[13px] shadow-2xl animate-in"
        >
          <CheckCircle className="w-4 h-4 text-emerald-400" aria-hidden="true" />
          {toast}
        </div>
      )}
    </div>
  );
}
