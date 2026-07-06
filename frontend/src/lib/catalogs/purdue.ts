/*
 * Purdue University — undergraduate college/major catalog (launch set).
 * College->major taxonomy from the official catalog; reuses existing i18n
 * labels where possible. Expandable as more programs are added.
 */

export const COLLEGE_MAJORS: Record<string, string[]> = {
  'College of Engineering': [
    'Aerospace Engineering',
    'Biomedical Engineering',
    'Chemical Engineering',
    'Civil Engineering',
    'Computer Engineering',
    'Electrical Engineering',
    'Industrial Engineering',
    'Materials Engineering',
    'Mechanical Engineering',
    'Nuclear Engineering',
    'Environmental and Ecological Engineering',
  ],
  'College of Science': [
    'Computer Science',
    'Data Science',
    'Mathematics',
    'Statistics',
    'Physics',
    'Chemistry',
    'Biology',
    'Biochemistry',
    'Actuarial Science',
    'Atmospheric Science',
    'Earth, Atmospheric, and Planetary Sciences',
  ],
  'College of Agriculture': [
    'Agricultural Economics',
    'Agronomy',
    'Animal Sciences',
    'Biochemistry',
    'Food Science',
    'Plant Science',
    'Natural Resources and Environmental Science',
  ],
  'Mitchell E. Daniels, Jr. School of Business': [
    'Accounting',
    'Economics',
    'Finance',
    'Management',
    'Marketing',
    'Business Analytics and Information Management',
  ],
  'College of Liberal Arts': [
    'Economics',
    'English',
    'History',
    'Political Science',
    'Psychology',
    'Sociology',
    'Communication',
    'Philosophy',
    'Linguistics',
  ],
  'College of Health and Human Sciences': [
    'Nursing',
    'Nutrition Science',
    'Public Health',
    'Psychological Sciences',
    'Human Development and Family Science',
    'Speech, Language, and Hearing Sciences',
  ],
  'Purdue Polytechnic Institute': [
    'Aviation Technology',
    'Construction Management',
    'Cybersecurity',
    'Mechanical Engineering Technology',
    'Computer and Information Technology',
  ],
  'College of Pharmacy': [
    'Pharmaceutical Sciences',
  ],
  'College of Education': [
    'Elementary Education',
    'Special Education',
  ],
};
