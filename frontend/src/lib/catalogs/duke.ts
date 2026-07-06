/*
 * Duke University — undergraduate college/major catalog (launch set).
 * College->major taxonomy from the official catalog; reuses existing i18n
 * labels where possible. Expandable as more programs are added.
 */

export const COLLEGE_MAJORS: Record<string, string[]> = {
  'Trinity College of Arts and Sciences': [
    'Computer Science',
    'Economics',
    'Biology',
    'Chemistry',
    'Physics',
    'Mathematics',
    'Statistical Science',
    'Psychology',
    'Neuroscience',
    'Political Science',
    'History',
    'English',
    'Sociology',
    'Public Policy',
    'Environmental Science',
    'Global Health',
    'Philosophy',
    'Biochemistry',
    'Evolutionary Anthropology',
    'Computer Science and Economics',
  ],
  'Pratt School of Engineering': [
    'Biomedical Engineering',
    'Civil Engineering',
    'Electrical and Computer Engineering',
    'Mechanical Engineering',
    'Environmental Engineering',
  ],
};
