// Clickable research-area chips that seed the interests box — the main matching
// lever. Terms are English (matched against English corpus keywords) and drawn
// from the corpus's most common research keywords, so a click surfaces real
// matches rather than a dead query. When the student's major/college is known
// we narrow the chips to that field; otherwise we fall back to the corpus-wide
// top domains. Patterns are matched as substrings against the lowercased
// "major college" string, so both catalog values and free-text majors work.

const GENERIC = [
  'Machine Learning', 'Artificial Intelligence', 'Data Science', 'Computer Vision',
  'Robotics', 'Embedded Systems', 'Neuroscience', 'Bioinformatics',
  'Materials Science', 'Chemistry', 'Quantitative Finance', 'Sustainability',
];

// Ordered: earlier groups contribute their interests first. A major can match
// several groups (e.g. "Computer Engineering" hits both CS and ECE) — hits are
// merged in order and de-duplicated.
const FIELD_INTERESTS: { test: RegExp; interests: string[] }[] = [
  { test: /data scien|analytic|informatics/, interests: ['Data Science', 'Machine Learning', 'Artificial Intelligence', 'Statistics', 'Computer Vision'] },
  { test: /comput|software/, interests: ['Machine Learning', 'Artificial Intelligence', 'Computer Vision', 'Software Engineering', 'Algorithms', 'Human-Computer Interaction', 'Data Science'] },
  { test: /electric|\bece\b|computer eng/, interests: ['Embedded Systems', 'Hardware', 'Machine Learning', 'Robotics', 'Quantum', 'Optimization', 'Computer Vision'] },
  { test: /mechanic|aerospace|aeronaut|\brobot/, interests: ['Robotics', 'Materials Science', 'Optimization', 'Machine Learning', 'Nanotechnology'] },
  { test: /bio.?med|bio.?eng|biomedical/, interests: ['Bioengineering', 'Biomedical', 'Bioinformatics', 'Computational Biology', 'Neuroscience', 'Biophysics'] },
  { test: /biolog|life scien|molecular|genetic|microbio|neuro|physiolog/, interests: ['Neuroscience', 'Genomics', 'Molecular Biology', 'Computational Biology', 'Genetics', 'Biochemistry', 'Evolution'] },
  { test: /chem/, interests: ['Organic Chemistry', 'Physical Chemistry', 'Chemical Biology', 'Materials Science', 'Biochemistry', 'Nanotechnology'] },
  { test: /physic|astro/, interests: ['Physics', 'Quantum', 'Biophysics', 'Materials Science', 'Nanotechnology', 'Optimization'] },
  { test: /math|statistic/, interests: ['Mathematics', 'Statistics', 'Optimization', 'Machine Learning', 'Data Science'] },
  { test: /material|metall|ceramic|polymer/, interests: ['Materials Science', 'Nanotechnology', 'Chemistry', 'Physics'] },
  { test: /econ|finance|account|business|marketing/, interests: ['Economics', 'Quantitative Finance', 'Finance', 'Macroeconomics', 'Labor Economics', 'Data Science'] },
  { test: /psych|cognit/, interests: ['Neuroscience', 'Mental Health', 'Human-Computer Interaction', 'Aging'] },
  { test: /environ|sustain|ecolog|climate|\bearth|geolog|atmospher|geograph/, interests: ['Climate Change', 'Sustainability', 'Ecology', 'Climate', 'Evolution'] },
  { test: /civil|architect|urban|construct|transport/, interests: ['Architecture', 'Sustainability', 'Materials Science', 'Optimization'] },
  { test: /agri|crop|animal scien|\bfood\b|plant|horticult|nutrition/, interests: ['Ecology', 'Genomics', 'Sustainability', 'Genetics', 'Evolution'] },
  { test: /nurs|public health|epidemiol|kinesiol|\bhealth\b|medicine|clinical/, interests: ['Mental Health', 'Neuroscience', 'Aging', 'Biomedical', 'Public Policy'] },
  { test: /politic|sociolog|anthropol|\bpolicy\b|government|\blaw\b|justice|international relations/, interests: ['Public Policy', 'Political Economy', 'Comparative Politics', 'Economics', 'Law'] },
  { test: /industrial|systems eng|operations|logistics|supply/, interests: ['Optimization', 'Machine Learning', 'Data Science', 'Statistics'] },
  { test: /educat|teaching/, interests: ['Education', 'Data Science', 'Machine Learning'] },
  { test: /music|\bart\b|\barts\b|\bdesign|theat|\bfilm|media|literat|english|histor|philosoph|cultur|language|linguist/, interests: ['Music', 'Architecture', 'Culture', 'Artificial Intelligence', 'Human-Computer Interaction'] },
];

const MAX_CHIPS = 12;

function collect(haystack: string): string[] {
  const hits: string[] = [];
  for (const { test, interests } of FIELD_INTERESTS) {
    if (test.test(haystack)) {
      for (const interest of interests) {
        if (!hits.includes(interest)) hits.push(interest);
      }
    }
  }
  return hits;
}

/**
 * Research-interest chip suggestions, narrowed to the student's field. The
 * major is the primary signal (Eric: "根据专业智能出结果"); the college is only a
 * fallback when the major is blank, so a broad college name like "Liberal Arts
 * & Sciences" never overrides a specific major. Falls back to the corpus-wide
 * top domains when nothing matches. Returns at most MAX_CHIPS terms.
 */
export function suggestInterests(major?: string, college?: string): string[] {
  const fromMajor = collect((major ?? '').toLowerCase());
  if (fromMajor.length) return fromMajor.slice(0, MAX_CHIPS);
  const fromCollege = collect((college ?? '').toLowerCase());
  return (fromCollege.length ? fromCollege : GENERIC).slice(0, MAX_CHIPS);
}
