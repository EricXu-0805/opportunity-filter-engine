'use client';

import { useState, useRef } from 'react';
import { X, Plus } from 'lucide-react';
import { useT } from '@/i18n/client';

interface MajorTagsProps {
  /** Raw major values already chosen (catalog values or free-typed minors). */
  selected: string[];
  /** Raw catalog majors for the chosen college, offered as suggestions. */
  options: string[];
  onChange: (majors: string[]) => void;
  /**
   * Maps a raw major value to its display label (localized). Catalog values go
   * through the majors i18n namespace; free-typed entries fall through to the
   * raw string, so this doubles as the identity for custom minors.
   */
  translate: (raw: string) => string;
}

/**
 * Multi-select for a student's *additional* majors and minors — the primary
 * major stays a single required dropdown; this captures double majors,
 * interdisciplinary combinations, and minors that broaden matching. Suggests
 * the college's catalog majors and, like SkillTags, accepts anything typed
 * (minors aren't in any catalog, so free-add is the only way to enter them).
 * Values feed the matcher's `secondary_interests` (extra majors + keywords).
 */
export default function MajorTags({ selected, options, onChange, translate }: MajorTagsProps) {
  const { t } = useT();
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const selectedSet = new Set(selected);
  const q = search.trim().toLowerCase();

  const available = options.filter(
    (m) => !selectedSet.has(m) && translate(m).toLowerCase().includes(q),
  );

  const trimmed = search.trim();
  const canAddCustom =
    trimmed.length > 0 &&
    !selectedSet.has(trimmed) &&
    !options.some((m) => translate(m).toLowerCase() === trimmed.toLowerCase());

  function addMajor(value: string) {
    onChange([...selected, value]);
    setSearch('');
    inputRef.current?.focus();
  }

  function removeMajor(value: string) {
    onChange(selected.filter((m) => m !== value));
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
        {selected.map((value) => (
          <span
            key={value}
            className="inline-flex items-center gap-1.5 pl-2.5 pr-1 py-1 rounded-lg ring-1 bg-indigo-50 text-indigo-700 ring-indigo-200 text-sm font-medium"
          >
            {translate(value)}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                removeMajor(value);
              }}
              className="p-0.5 rounded hover:bg-black/5 transition-colors"
              aria-label={t('home.form.additionalMajorsRemove', { major: translate(value) })}
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
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                if (trimmed.length === 0) return;
                if (available.length > 0) addMajor(available[0]);
                else if (canAddCustom) addMajor(trimmed);
              }
            }}
            placeholder={
              selected.length === 0
                ? t('home.form.additionalMajorsPlaceholder')
                : t('home.form.additionalMajorsAddMore')
            }
            className="flex-1 text-sm bg-transparent outline-none placeholder:text-gray-400"
          />
        </div>
      </div>

      {isOpen && (available.length > 0 || canAddCustom) && (
        <div className="absolute z-20 mt-1.5 w-full max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-xl shadow-lg">
          {available.map((m) => (
            <button
              key={m}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                addMajor(m);
              }}
              className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-indigo-50 hover:text-indigo-700 transition-colors first:rounded-t-xl last:rounded-b-xl"
            >
              {translate(m)}
            </button>
          ))}
          {canAddCustom && (
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                addMajor(trimmed);
              }}
              className="w-full flex items-center gap-2 text-left px-4 py-2.5 text-sm font-medium text-indigo-700 hover:bg-indigo-50 transition-colors border-t border-gray-100 first:border-t-0 first:rounded-t-xl last:rounded-b-xl"
            >
              <Plus className="w-3.5 h-3.5 shrink-0" />
              {t('home.form.additionalMajorsAddCustom', { major: trimmed })}
            </button>
          )}
        </div>
      )}

      <p className="mt-1.5 text-[11px] text-gray-400 leading-snug">
        {t('home.form.additionalMajorsHint')}
      </p>
    </div>
  );
}
