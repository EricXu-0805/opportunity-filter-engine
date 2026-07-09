/*
 * Northwestern University — undergraduate college/major catalog.
 * College->major taxonomy across the university's schools; reuses existing
 * i18n labels where possible. Faculty coverage may trail (arts & sciences
 * first); the catalog reflects what students can study.
 */

export const COLLEGE_MAJORS: Record<string, string[]> = {
  "Weinberg College of Arts and Sciences": [
    "Anthropology",
    "Art History",
    "Astronomy",
    "Chemistry",
    "Classics",
    "Economics",
    "English",
    "French",
    "Italian",
    "German",
    "History",
    "Linguistics",
    "Mathematics",
    "Molecular Biosciences",
    "Neuroscience",
    "Philosophy",
    "Physics",
    "Political Science",
    "Psychology",
    "Religious Studies",
    "Sociology",
    "Spanish",
    "Portuguese",
    "Statistics",
    "Earth Science",
    "Environmental Sciences",
    "Gender & Sexuality Studies",
    "Biochemistry",
  ],
  "McCormick School of Engineering and Applied Science": [
    "Biomedical Engineering",
    "Chemical Engineering",
    "Civil Engineering",
    "Computer Science",
    "Electrical Engineering",
    "Industrial Engineering",
    "Materials Science",
    "Mechanical Engineering",
    "Environmental Engineering",
  ],
  "Medill School of Journalism": [
    "Journalism",
  ],
  "School of Education and Social Policy": [
    "Human Development",
    "Social Policy",
    "Learning Sciences",
  ],
  "Bienen School of Music": [
    "Music",
    "Music Composition",
  ],
  "School of Communication": [
    "Communication Studies",
    "Theatre",
    "Radio/Television/Film",
  ],
  "Pritzker School of Law": [
    "Law",
    "Legal Studies",
  ],
};
