'use client';

import { useState, useRef } from 'react';
import { X, Plus } from 'lucide-react';
import type { SkillWithLevel, SkillLevel } from '@/lib/types';

const ALL_SKILLS = [
  'Python', 'Java', 'C++', 'C', 'C#', 'JavaScript', 'TypeScript',
  'R', 'MATLAB', 'Rust', 'Go', 'Kotlin', 'Swift', 'Ruby', 'PHP',
  'SQL', 'NoSQL', 'HTML/CSS',
  'PyTorch', 'TensorFlow', 'scikit-learn', 'Keras', 'HuggingFace',
  'pandas', 'NumPy', 'SciPy', 'OpenCV', 'NLTK', 'spaCy',
  'React', 'Next.js', 'Vue', 'Angular', 'Node.js', 'Express',
  'Flask', 'Django', 'FastAPI', 'Spring Boot',
  'AWS', 'GCP', 'Azure', 'Firebase',
  'Docker', 'Kubernetes', 'Git', 'Linux', 'Bash',
  'Figma', 'Adobe Suite', 'Unity', 'Unreal Engine',
  'ROS', 'Arduino', 'Raspberry Pi', 'FPGA', 'Verilog', 'VHDL',
  'Solidworks', 'AutoCAD', 'ANSYS', 'COMSOL',
  'LaTeX', 'Excel', 'Tableau', 'Power BI',
  'SPSS', 'SAS', 'Stata', 'Mathematica',
  'Blender', 'Maya', 'Photoshop', 'Illustrator',
] as const;

const LEVEL_CONFIG: Record<SkillLevel, { label: string; color: string; bg: string; ring: string }> = {
  beginner:    { label: 'Beginner',    color: 'text-slate-600',  bg: 'bg-slate-100',  ring: 'ring-slate-200' },
  experienced: { label: 'Experienced', color: 'text-indigo-700',   bg: 'bg-indigo-50',    ring: 'ring-indigo-200' },
  expert:      { label: 'Expert',      color: 'text-violet-700', bg: 'bg-violet-50',  ring: 'ring-violet-200' },
};

const LEVELS: SkillLevel[] = ['beginner', 'experienced', 'expert'];

interface SkillTagsProps {
  selected: SkillWithLevel[];
  onChange: (skills: SkillWithLevel[]) => void;
}

export default function SkillTags({ selected, onChange }: SkillTagsProps) {
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
        return { ...s, level: LEVELS[(idx + 1) % LEVELS.length] };
      }),
    );
  }

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
          return (
            <span
              key={skill.name}
              className={`inline-flex items-center gap-1.5 pl-2.5 pr-1 py-1 rounded-lg ring-1 ${cfg.bg} ${cfg.color} ${cfg.ring} text-sm font-medium group transition-all duration-200`}
            >
              {skill.name}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  cycleLevel(skill.name);
                }}
                className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${cfg.bg} hover:brightness-95 transition-all cursor-pointer select-none`}
                title={`Click to change level (${cfg.label})`}
              >
                {cfg.label}
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  removeSkill(skill.name);
                }}
                className="p-0.5 rounded hover:bg-black/5 transition-colors"
                aria-label={`Remove ${skill.name}`}
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
                if (available.length > 0) addSkill(available[0]);
                else if (canAddCustom) addSkill(trimmed);
              }
            }}
            placeholder={selected.length === 0 ? 'Select skills...' : 'Add more...'}
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
              Add &ldquo;{trimmed}&rdquo;
            </button>
          )}
        </div>
      )}
    </div>
  );
}
