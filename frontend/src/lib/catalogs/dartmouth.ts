/*
 * Dartmouth College — undergraduate college/major catalog.
 * Arts & Sciences' four divisions plus the Thayer School of Engineering;
 * reuses existing i18n labels where possible. Majors reflect Dartmouth's
 * undergraduate majors (AB), not graduate-only programs.
 */

export const COLLEGE_MAJORS: Record<string, string[]> = {
  'Arts and Humanities': [
    'Art History',
    'Studio Art',
    'Classics',
    'Comparative Literature',
    'English',
    'Film and Media Studies',
    'French',
    'German Studies',
    'Italian',
    'Spanish',
    'Middle Eastern Studies',
    'Music',
    'Philosophy',
    'Religion',
    'Russian',
    'Theater',
  ],
  'Sciences': [
    'Biological Sciences',
    'Chemistry',
    'Computer Science',
    'Earth Sciences',
    'Mathematics',
    'Physics',
    'Astronomy',
    'Psychological and Brain Sciences',
  ],
  'Social Sciences': [
    'Anthropology',
    'Economics',
    'Geography',
    'Government',
    'History',
    'Quantitative Social Science',
    'Sociology',
  ],
  'Interdisciplinary Programs': [
    'African and African American Studies',
    'Asian Societies, Cultures, and Languages',
    'Cognitive Science',
    'Environmental Studies',
    'Latin American, Latino and Caribbean Studies',
    'Linguistics',
    'Native American and Indigenous Studies',
    "Women's, Gender, and Sexuality Studies",
  ],
  'Thayer School of Engineering': [
    'Engineering Sciences',
    'Biomedical Engineering',
  ],
};
