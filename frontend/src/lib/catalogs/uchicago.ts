/*
 * University of Chicago — undergraduate major catalog.
 * Compiled 2026-07-04 from the 2025-26 College catalog's List of Majors (56
 * majors; the live 2026-27 list is identical); do not hand-edit.
 * Verified against:
 *   http://collegecatalog.uchicago.edu/archives/2025-2026/thecollege/programsofstudy/
 *   https://college.uchicago.edu/api/v1/programs (division tags)
 * Notes: UChicago's single undergraduate College organizes majors by collegiate
 * division, so the switcher renders division→major. The Humanities division is
 * listed under its current official name (Arts & Humanities Collegiate
 * Division). The New Collegiate Division hosts no majors in 2025-26 (its
 * historic majors were re-homed: Law, Letters, and Society + HIPS to Social
 * Sciences; Fundamentals to Arts & Humanities) and is therefore omitted.
 * Molecular Engineering is administered by the Pritzker School of Molecular
 * Engineering but listed by the College under Physical Sciences. Minors and
 * minor-only programs (e.g. Geographic Information Science) are excluded.
 */

export const COLLEGE_MAJORS: Record<string, string[]> = {
  'Biological Sciences Collegiate Division': [
    'Biological Sciences',
    'Neuroscience',
  ],
  'Arts & Humanities Collegiate Division': [
    'Archaeology',
    'Art History',
    'Cinema and Media Studies',
    'Classical Studies',
    'Cognitive Science',
    'Comparative Literature',
    'Creative Writing',
    'East Asian Languages and Civilizations',
    'English Language and Literature',
    'Fundamentals: Issues and Texts',
    'Germanic Studies',
    'Inquiry and Research in the Humanities',
    'Jewish Studies',
    'Linguistics',
    'Media Arts and Design',
    'Medieval Studies',
    'Middle Eastern Studies',
    'Music',
    'Philosophy',
    'Religious Studies',
    'Romance Languages and Literatures',
    'Russian and East European Studies',
    'South Asian Languages and Civilizations',
    'Theater and Performance Studies',
    'Visual Arts',
  ],
  'Physical Sciences Collegiate Division': [
    'Astrophysics',
    'Biological Chemistry',
    'Chemistry',
    'Climate and Sustainable Growth',
    'Computational and Applied Mathematics',
    'Computer Science',
    'Data Science',
    'Environmental Science',
    'Geophysical Sciences',
    'Mathematics',
    'Molecular Engineering',
    'Physics',
    'Statistics',
  ],
  'Social Sciences Collegiate Division': [
    'Anthropology',
    'Comparative Human Development',
    'Economics',
    'Environment, Geography, and Urbanization',
    'Gender and Sexuality Studies',
    'Global Studies',
    'History',
    'History, Philosophy, and Social Studies of Science and Medicine',
    'Human Rights',
    'Latin American and Caribbean Studies',
    'Law, Letters, and Society',
    'Political Science',
    'Psychology',
    'Public Policy Studies',
    'Race, Diaspora, and Indigeneity',
    'Sociology',
  ],
};
