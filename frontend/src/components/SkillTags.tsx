'use client';

import { useState, useRef } from 'react';
import { X, Plus } from 'lucide-react';

const ALL_SKILLS = [
  'Python',
  'Java',
  'C++',
  'C',
  'JavaScript',
  'R',
  'MATLAB',
  'PyTorch',
  'TensorFlow',
  'pandas',
  'SQL',
  'Git',
  'Linux',
  'React',
  'Docker',
] as const;

interface SkillTagsProps {
  selected: string[];
  onChange: (skills: string[]) => void;
}

export default function SkillTags({ selected, onChange }: SkillTagsProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const available = ALL_SKILLS.filter(
    (s) =>
      !selected.includes(s) &&
      s.toLowerCase().includes(search.toLowerCase()),
  );

  function addSkill(skill: string) {
    onChange([...selected, skill]);
    setSearch('');
    inputRef.current?.focus();
  }

  function removeSkill(skill: string) {
    onChange(selected.filter((s) => s !== skill));
  }

  return (
    <div className="relative">
      {/* Selected chips */}
      <div
        className="min-h-[44px] flex flex-wrap items-center gap-2 px-3 py-2 border border-gray-300 rounded-xl bg-white focus-within:ring-2 focus-within:ring-blue-500/30 focus-within:border-blue-400 transition-all cursor-text"
        onClick={() => {
          setIsOpen(true);
          inputRef.current?.focus();
        }}
      >
        {selected.map((skill) => (
          <span
            key={skill}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-blue-50 text-blue-700 text-sm font-medium group"
          >
            {skill}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                removeSkill(skill);
              }}
              className="ml-0.5 p-0.5 rounded hover:bg-blue-100 transition-colors"
              aria-label={`Remove ${skill}`}
            >
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
        <div className="flex items-center gap-1 flex-1 min-w-[100px]">
          <Plus className="w-3.5 h-3.5 text-gray-400" />
          <input
            ref={inputRef}
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onFocus={() => setIsOpen(true)}
            onBlur={() => setTimeout(() => setIsOpen(false), 200)}
            placeholder={selected.length === 0 ? 'Select skills...' : 'Add more...'}
            className="flex-1 text-sm bg-transparent outline-none placeholder:text-gray-400"
          />
        </div>
      </div>

      {/* Dropdown */}
      {isOpen && available.length > 0 && (
        <div className="absolute z-20 mt-1.5 w-full max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-xl shadow-lg">
          {available.map((skill) => (
            <button
              key={skill}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                addSkill(skill);
              }}
              className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-blue-50 hover:text-blue-700 transition-colors first:rounded-t-xl last:rounded-b-xl"
            >
              {skill}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
