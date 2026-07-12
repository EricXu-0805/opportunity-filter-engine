/*
 * Caltech — undergraduate college/major catalog.
 * The six academic divisions and their undergraduate options; reuses
 * existing i18n labels where possible.
 */

export const COLLEGE_MAJORS: Record<string, string[]> = {
  'Division of Biology and Biological Engineering': [
    'Biology',
    'Bioengineering',
    'Neurobiology',
  ],
  'Division of Chemistry and Chemical Engineering': [
    'Chemistry',
    'Chemical Engineering',
  ],
  'Division of Engineering and Applied Science': [
    'Applied Physics',
    'Computer Science',
    'Electrical Engineering',
    'Environmental Science and Engineering',
    'Information and Data Sciences',
    'Materials Science',
    'Mechanical Engineering',
  ],
  'Division of Geological and Planetary Sciences': [
    'Geobiology',
    'Geochemistry',
    'Geology',
    'Geophysics',
    'Planetary Science',
  ],
  'Division of the Humanities and Social Sciences': [
    'Business, Economics, and Management',
    'Economics',
    'English',
    'History',
    'History and Philosophy of Science',
    'Philosophy',
    'Political Science',
  ],
  'Division of Physics, Mathematics and Astronomy': [
    'Applied and Computational Mathematics',
    'Astrophysics',
    'Mathematics',
    'Physics',
  ],
};
