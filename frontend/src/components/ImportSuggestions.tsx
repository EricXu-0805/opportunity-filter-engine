type Props = {
  skills: string[];
  summary?: string;
  t: (key: string) => string;
};

export default function ImportSuggestions({ skills, summary, t }: Props) {
  if (!skills.length && !summary) return null;
  return (
    <section className="my-4 rounded-xl border border-amber-200 bg-amber-50/50 p-4" aria-label={t('import.suggestionsTitle')}>
      <h3 className="text-sm font-semibold text-gray-800">{t('import.suggestionsTitle')}</h3>
      <p className="mt-1 text-xs leading-relaxed text-gray-600">{t('import.suggestionsNote')}</p>
      {skills.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {skills.map((skill) => (
            <span key={skill} className="max-w-full break-words rounded-lg border border-gray-200 bg-white px-2.5 py-1 text-xs text-gray-700">{skill}</span>
          ))}
        </div>
      )}
      {summary && (
        <details className="mt-3 text-sm text-gray-700">
          <summary className="cursor-pointer font-medium">{t('import.suggestedSummary')}</summary>
          <p className="mt-2 whitespace-pre-wrap break-words">{summary}</p>
        </details>
      )}
    </section>
  );
}
