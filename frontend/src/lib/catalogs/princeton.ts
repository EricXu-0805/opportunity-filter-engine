/*
 * Princeton — undergraduate concentration catalog.
 * Compiled 2026-06-26 from Princeton's published degree programs; do not hand-edit.
 * Verified against:
 *   https://ua.princeton.edu/fields-study/departmental-majors-degree-programs
 *   https://www.princeton.edu/academics/areas-study
 * Notes: Princeton organizes undergraduate study by departmental "concentrations"
 * rather than enrollment colleges; we group them under the four academic divisions
 * plus the School of Architecture so the switcher renders a familiar college→major
 * tree. Computer Science is offered as both an A.B. (Natural Sciences) and a B.S.E.
 * (Engineering) and so appears under both divisions. Certificate programs, minors,
 * and the independent concentration are excluded.
 */

export const COLLEGE_MAJORS: Record<string, string[]> = {
  'School of Engineering and Applied Science': [
    'Chemical and Biological Engineering',
    'Civil and Environmental Engineering',
    'Computer Science',
    'Electrical and Computer Engineering',
    'Mechanical and Aerospace Engineering',
    'Operations Research and Financial Engineering',
  ],
  'Humanities': [
    'Art and Archaeology',
    'Classics',
    'Comparative Literature',
    'East Asian Studies',
    'English',
    'French and Italian',
    'German',
    'Music',
    'Near Eastern Studies',
    'Philosophy',
    'Religion',
    'Slavic Languages and Literatures',
    'Spanish and Portuguese',
  ],
  'Social Sciences': [
    'African American Studies',
    'Anthropology',
    'Economics',
    'History',
    'Politics',
    'Psychology',
    'Public and International Affairs',
    'Sociology',
  ],
  'Natural Sciences': [
    'Astrophysical Sciences',
    'Chemistry',
    'Computer Science',
    'Ecology and Evolutionary Biology',
    'Geosciences',
    'Mathematics',
    'Molecular Biology',
    'Neuroscience',
    'Physics',
  ],
  'School of Architecture': [
    'Architecture',
  ],
};
