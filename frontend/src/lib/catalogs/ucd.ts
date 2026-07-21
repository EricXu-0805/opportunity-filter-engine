/*
 * UC Davis — undergraduate college/major catalog.
 * Engineering + Letters & Science + Biological Sciences + Agricultural &
 * Environmental Sciences (the four colleges covered by the onboarded
 * SiteFarm department directories).
 */

export const COLLEGE_MAJORS: Record<string, string[]> = {
  'College of Engineering': [
    'Computer Science',
    'Electrical and Computer Engineering',
    'Mechanical Engineering',
    'Aerospace Engineering',
    'Biomedical Engineering',
    'Civil Engineering',
    'Environmental Engineering',
    'Biological Systems Engineering',
  ],
  'College of Letters and Science': [
    'Physics',
    'Astronomy',
    'Chemistry',
    'Statistics',
    'Economics',
    'Psychology',
    'Sociology',
    'Anthropology',
    'Political Science',
    'Communication',
    'History',
    'English',
    'Philosophy',
    'Linguistics',
  ],
  'College of Biological Sciences': [
    'Molecular and Cellular Biology',
    'Neurobiology, Physiology and Behavior',
    'Evolution and Ecology',
    'Microbiology',
    'Genetics',
    'Biochemistry',
  ],
  'College of Agricultural and Environmental Sciences': [
    'Agricultural and Resource Economics',
    'Animal Science',
    'Food Science and Technology',
    'Entomology',
    'Viticulture and Enology',
    'Human Development',
    'Textiles and Clothing',
  ],
};
