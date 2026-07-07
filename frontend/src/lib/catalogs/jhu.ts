/*
 * Johns Hopkins University — undergraduate college/major catalog.
 * College->major taxonomy across the university's schools; reuses existing
 * i18n labels where possible. Faculty coverage may trail (arts & sciences
 * first); the catalog reflects what students can study.
 */

export const COLLEGE_MAJORS: Record<string, string[]> = {
  "Krieger School of Arts and Sciences": [
    "Biology",
    "Chemistry",
    "Physics",
    "Astronomy",
    "Mathematics",
    "Applied Mathematics",
    "Biophysics",
    "Cognitive Science",
    "Economics",
    "English",
    "History",
    "Art History",
    "Philosophy",
    "Political Science",
    "Psychology",
    "Neuroscience",
    "Sociology",
    "Anthropology",
    "Classics",
    "Near Eastern Studies",
    "Creative Writing",
    "Earth Sciences",
    "Environmental Science",
    "Public Health",
    "International Studies",
  ],
  "Whiting School of Engineering": [
    "Biomedical Engineering",
    "Computer Science",
    "Electrical Engineering",
    "Computer Engineering",
    "Chemical Engineering",
    "Civil Engineering",
    "Mechanical Engineering",
    "Materials Science",
    "Environmental Engineering",
    "Applied Mathematics and Statistics",
    "Robotics",
  ],
  "Bloomberg School of Public Health": [
    "Public Health",
    "Environmental Health",
  ],
  "School of Nursing": [
    "Nursing",
  ],
  "Peabody Institute": [
    "Music",
    "Music Composition",
  ],
};
