/** College → major/department mappings for UIUC */
export const COLLEGE_MAJORS: Record<string, string[]> = {
  'Grainger College of Engineering': [
    'Electrical & Computer Engineering (ECE)',
    'Computer Science (CS)',
    'Mechanical Science & Engineering (MechSE)',
    'Civil & Environmental Engineering (CEE)',
    'Materials Science & Engineering (MatSE)',
    'Aerospace Engineering (AE)',
    'Bioengineering (BioE)',
    'Industrial & Enterprise Systems Engineering (ISE)',
    'Nuclear, Plasma, & Radiological Engineering (NPRE)',
    'Physics (Engineering Physics)',
  ],
  'Liberal Arts & Sciences (LAS)': [
    'Statistics',
    'Mathematics',
    'Chemistry',
    'Biology',
    'Psychology',
    'Economics',
    'Political Science',
    'English',
    'History',
    'Sociology',
    'Philosophy',
    'Linguistics',
    'Molecular & Cellular Biology',
    'Integrative Biology',
  ],
  'Gies College of Business': [
    'Finance',
    'Accountancy',
    'Information Systems',
    'Supply Chain Management',
    'Marketing',
    'Management',
  ],
  'College of ACES': [
    'Agricultural & Biological Engineering',
    'Animal Sciences',
    'Crop Sciences',
    'Food Science & Human Nutrition',
    'Natural Resources & Environmental Sciences',
    'Agricultural & Consumer Economics',
  ],
  'College of Fine & Applied Arts': [
    'Architecture',
    'Art & Design',
    'Dance',
    'Landscape Architecture',
    'Music',
    'Theatre',
    'Urban & Regional Planning',
  ],
  'School of Information Sciences (iSchool)': [
    'Information Sciences',
    'Library & Information Science',
  ],
  'College of Applied Health Sciences': [
    'Kinesiology',
    'Community Health',
    'Recreation, Sport & Tourism',
    'Speech & Hearing Science',
  ],
  'College of Education': [
    'Curriculum & Instruction',
    'Education Policy',
    'Special Education',
    'Learning Design & Leadership',
  ],
  'College of Media': [
    'Journalism',
    'Advertising',
    'Media & Cinema Studies',
  ],
  'College of Veterinary Medicine': [
    'Veterinary Medicine',
    'Comparative Biosciences',
    'Pathobiology',
  ],
};

export const COLLEGES = Object.keys(COLLEGE_MAJORS);

export const GRADES = ['Freshman', 'Sophomore', 'Junior', 'Senior'] as const;
