'use client';

import { useState, useRef } from 'react';
import { X, Plus } from 'lucide-react';
import type { SkillWithLevel, SkillLevel } from '@/lib/types';
import { skillNeedsConfirming } from '@/lib/skill-evidence';
import { useT } from '@/i18n/client';

// A multi-domain STARTER set, not a closed list — students can type any skill we
// don't carry (see the custom-add path + the always-visible hint below the input).
// Grouped by domain so coverage gaps are visible; wet-lab / bio-chem and
// mechanical were the biggest holes for non-CS majors.
const ALL_SKILLS = [
  // Programming languages
  'Python', 'Java', 'C++', 'C', 'C#', 'JavaScript', 'TypeScript',
  'R', 'MATLAB', 'Rust', 'Go', 'Kotlin', 'Swift', 'Ruby', 'PHP', 'Julia',
  'SQL', 'NoSQL', 'HTML/CSS',
  // ML / AI / data
  'PyTorch', 'TensorFlow', 'scikit-learn', 'Keras', 'JAX', 'HuggingFace', 'LangChain',
  'pandas', 'NumPy', 'SciPy', 'OpenCV', 'NLTK', 'spaCy', 'Jupyter',
  'Spark', 'Hadoop', 'Databricks', 'dbt', 'Airflow',
  // Web / backend / infra
  'React', 'Next.js', 'Vue', 'Angular', 'Node.js', 'Express',
  'Flask', 'Django', 'FastAPI', 'Spring Boot',
  'GraphQL', 'PostgreSQL', 'MongoDB', 'Redis', 'Kafka',
  'AWS', 'GCP', 'Azure', 'Firebase',
  'Docker', 'Kubernetes', 'Terraform', 'Git', 'Linux', 'Bash', 'CI/CD',
  // Hardware / embedded / EDA
  'ROS', 'Arduino', 'Raspberry Pi', 'STM32', 'FPGA', 'Verilog', 'VHDL', 'SystemVerilog',
  'Vivado', 'Quartus', 'Altium', 'KiCad', 'Cadence', 'LTspice', 'Eagle', 'Embedded C',
  // Mechanical / CAD / simulation
  'Solidworks', 'AutoCAD', 'Fusion 360', 'CATIA', 'Creo', 'ANSYS', 'Abaqus', 'COMSOL',
  'Simulink', 'LabVIEW', '3D Printing', 'GD&T',
  // Wet lab / biology / chemistry
  'PCR', 'qPCR', 'CRISPR', 'Cell Culture', 'Western Blot', 'Flow Cytometry',
  'Mass Spectrometry', 'HPLC', 'NMR', 'Microscopy', 'Gel Electrophoresis', 'ELISA',
  'DNA/RNA Sequencing', 'Immunohistochemistry', 'Chromatography', 'Titration', 'Spectroscopy',
  'Bioinformatics', 'Biopython', 'Bioconductor', 'BLAST',
  // Statistics / analysis / GIS
  'LaTeX', 'Excel', 'Tableau', 'Power BI', 'SPSS', 'SAS', 'Stata', 'JMP',
  'Mathematica', 'Stan', 'Regression Analysis', 'ArcGIS', 'QGIS', 'Remote Sensing',
  // Business / product
  'Product Management', 'Financial Modeling', 'Bloomberg Terminal', 'QuickBooks',
  // Research / communication
  'Technical Writing', 'Data Analysis', 'Literature Review',
  // Design / creative
  'Figma', 'Adobe Suite', 'Unity', 'Unreal Engine',
  'Blender', 'Maya', 'Photoshop', 'Illustrator',
] as const;

const LEVEL_CONFIG: Record<SkillLevel, { color: string; bg: string; ring: string }> = {
  beginner:    { color: 'text-slate-600',  bg: 'bg-slate-100',  ring: 'ring-slate-200' },
  experienced: { color: 'text-indigo-700', bg: 'bg-indigo-50',  ring: 'ring-indigo-200' },
  expert:      { color: 'text-violet-700', bg: 'bg-violet-50',  ring: 'ring-violet-200' },
};

const LEVELS: SkillLevel[] = ['beginner', 'experienced', 'expert'];

interface SkillTagsProps {
  selected: SkillWithLevel[];
  onChange: (skills: SkillWithLevel[]) => void;
}

export default function SkillTags({ selected, onChange }: SkillTagsProps) {
  const { t } = useT();
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const selectedNames = new Set(selected.map((s) => s.name));

  const available = ALL_SKILLS.filter(
    (s) =>
      !selectedNames.has(s) &&
      s.toLowerCase().includes(search.toLowerCase()),
  );

  // Let users add a skill we don't carry as a preset (the ~80 ALL_SKILLS
  // are a starter set, not a closed list). Offered only when the typed
  // value isn't already selected or an exact preset (case-insensitive).
  const trimmed = search.trim();
  const canAddCustom =
    trimmed.length > 0 &&
    !selectedNames.has(trimmed) &&
    !ALL_SKILLS.some((s) => s.toLowerCase() === trimmed.toLowerCase());

  function addSkill(name: string) {
    onChange([...selected, { name, level: 'beginner' }]);
    setSearch('');
    inputRef.current?.focus();
  }

  function removeSkill(name: string) {
    onChange(selected.filter((s) => s.name !== name));
  }

  function cycleLevel(name: string) {
    onChange(
      selected.map((s) => {
        if (s.name !== name) return s;
        const idx = LEVELS.indexOf(s.level);
        // Choosing the level IS the confirmation. An imported skill arrives
        // unclaimed; the moment the student sets where they actually stand, the
        // level is their own word and may back an outward claim.
        return {
          ...s,
          level: LEVELS[(idx + 1) % LEVELS.length],
          confirmed: true,
        };
      }),
    );
  }

  // Named rather than counted per chip: the student needs one sentence telling
  // them why some chips look different and what to do, not a badge on each.
  const unsettledCount = selected.filter(skillNeedsConfirming).length;

  return (
    <div className="relative">
      <div
        className="min-h-[44px] flex flex-wrap items-center gap-2 px-3 py-2 border border-gray-300 rounded-xl bg-white focus-within:ring-2 focus-within:ring-indigo-500/30 focus-within:border-indigo-400 transition-all cursor-text"
        onClick={() => {
          setIsOpen(true);
          inputRef.current?.focus();
        }}
      >
        {selected.map((skill) => {
          const cfg = LEVEL_CONFIG[skill.level];
          const levelLabel = t(`skills.levels.${skill.level}`);
          // An import found the NAME on a page; it never learned how well the
          // student knows it. A legacy `experienced` is the same story with the
          // provenance missing. Either way the chip reads as unsettled — dashed
          // rather than solid — and one tap on the level both sets and settles it.
          const unsettled = skillNeedsConfirming(skill);
          return (
            <span
              key={skill.name}
              // Tailwind has no dashed RING, so an unsettled chip swaps the
              // ring for the dashed border this codebase already uses for
              // provisional things, in the amber of the hint line below.
              className={`inline-flex items-center gap-1.5 pl-2.5 pr-1 py-1 rounded-lg ${cfg.bg} ${cfg.color} ${unsettled ? 'border border-dashed border-amber-300' : `ring-1 ${cfg.ring}`} text-sm font-medium group transition-all duration-200`}
            >
              {skill.name}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  cycleLevel(skill.name);
                }}
                className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${cfg.bg} hover:brightness-95 transition-all cursor-pointer select-none`}
                title={
                  unsettled && skill.source
                    ? t(`skills.importedFrom.${skill.source}`)
                    : unsettled
                      ? t('skills.confirmLevelTitle')
                      : t('skills.cycleLevelTitle', { level: levelLabel })
                }
              >
                {levelLabel}
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  removeSkill(skill.name);
                }}
                className="p-0.5 rounded hover:bg-black/5 transition-colors"
                aria-label={t('skills.remove', { skill: skill.name })}
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          );
        })}
        <div className="flex items-center gap-1 flex-1 min-w-[100px]">
          <Plus className="w-3.5 h-3.5 text-gray-400" />
          <input
            ref={inputRef}
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onFocus={() => setIsOpen(true)}
            onBlur={() => setTimeout(() => setIsOpen(false), 200)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                if (trimmed.length === 0) return;
                if (available.length > 0) addSkill(available[0]);
                else if (canAddCustom) addSkill(trimmed);
              }
            }}
            placeholder={selected.length === 0 ? t('skills.searchPlaceholder') : t('skills.addMorePlaceholder')}
            className="flex-1 text-sm bg-transparent outline-none placeholder:text-gray-400"
          />
        </div>
      </div>

      {isOpen && (available.length > 0 || canAddCustom) && (
        <div className="absolute z-20 mt-1.5 w-full max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-xl shadow-lg">
          {available.map((skill) => (
            <button
              key={skill}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                addSkill(skill);
              }}
              className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-indigo-50 hover:text-indigo-700 transition-colors first:rounded-t-xl last:rounded-b-xl"
            >
              {skill}
            </button>
          ))}
          {canAddCustom && (
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                addSkill(trimmed);
              }}
              className="w-full flex items-center gap-2 text-left px-4 py-2.5 text-sm font-medium text-indigo-700 hover:bg-indigo-50 transition-colors border-t border-gray-100 first:border-t-0 first:rounded-t-xl last:rounded-b-xl"
            >
              <Plus className="w-3.5 h-3.5 shrink-0" />
              {t('skills.addCustom', { skill: trimmed })}
            </button>
          )}
        </div>
      )}

      {unsettledCount > 0 && (
        /* Says what happened and what to do, in one line. Without it the dashed
           chips are just an unexplained style, and the levels stay unset — which
           is what keeps every generated email and resume at "exposure". */
        <p role="status" className="mt-1.5 text-[11px] text-amber-700 leading-snug">
          {t('skills.confirmImportedHint', { count: unsettledCount })}
        </p>
      )}

      {/* Always-visible hint so students know the presets aren't a closed list —
          custom-add was previously only discoverable inside the dropdown. */}
      <p className="mt-1.5 text-[11px] text-gray-400 leading-snug">
        {t('skills.addAnyHint')}
      </p>
    </div>
  );
}
