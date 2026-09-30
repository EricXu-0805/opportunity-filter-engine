/** Read new and historical imports without rewriting the saved record. */
export function importSuggestions(extra: Record<string, unknown> | undefined) {
  const values = extra ?? {};
  const skills: string[] = [];
  const seen = new Set<string>();
  // Older model outputs used qualification-shaped keys without provenance.
  // Their original strings remain available, but they cannot establish a rule.
  for (const key of ['suggested_skills', 'skills_required', 'skills_preferred']) {
    const items = values[key];
    if (!Array.isArray(items)) continue;
    for (const item of items) {
      if (typeof item !== 'string' || !item.trim()) continue;
      const label = item.trim();
      if (seen.has(label.toLowerCase())) continue;
      seen.add(label.toLowerCase());
      skills.push(label);
    }
  }
  return {
    skills,
    summary: typeof values.suggested_description === 'string' ? values.suggested_description : '',
  };
}
