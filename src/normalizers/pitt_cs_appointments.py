"""Full-time CS appointments with separately published Pitt department and college profiles."""
from typing import NamedTuple


class Appointment(NamedTuple):
    college_name: str
    college_url: str
    published_id: str


_PROFILES: dict[tuple[str, str], Appointment] = {}
COLLEGE_ID_NAMES: dict[str, tuple[str, str]] = {}


def _register(name: str, slug: str, published_id: str,
              college_name: str = "", college_slug: str = "") -> None:
    college_name = college_name or name
    college_url = "https://www.sci.pitt.edu/people/" + (college_slug or slug)
    department_url = "https://www.cs.pitt.edu/people/full-time-faculty/" + slug
    record = Appointment(college_name, college_url, published_id)
    _PROFILES[(department_url, name)] = record
    _PROFILES[(college_url, college_name)] = record
    # A saved department ID may retain the department spelling on the college link.
    _PROFILES[(college_url, name)] = record
    if college_name != name:
        COLLEGE_ID_NAMES[college_url] = (college_name, name)


# Department name, department slug, original saved ID, and any college spelling
# or profile slug that differs. Each pair was observed on the two campus sites.
for pair in (
    ("Wonsun Ahn", "wonsun-ahn", "faculty-pitt-cs-37b1191a"),
    ("Amy Babay", "amy-babay", "faculty-pitt-cs-56354f0d", "Amy Babay", "amy-babay-0"),
    ("Marina Barsky", "marina-barsky", "faculty-pitt-cs-3f9ffe0f"),
    ("Jacob Biehl", "jacob-biehl", "faculty-pitt-cs-0c5994c8"),
    ("Bruce Childers", "bruce-childers", "faculty-pitt-cs-e47a8796", "Bruce R. Childers", "bruce-r-childers"),
    ("Panos Chrysanthis", "panos-chrysanthis", "faculty-pitt-cs-c488d791"),
    ("Paul Cohen", "paul-cohen", "faculty-pitt-cs-6314125a"),
    ("Nicholas Farnan", "nicholas-farnan", "faculty-pitt-cs-2ba882dd", "Nicholas L. Farnan", "nicholas-l-farnan"),
    ("William Garrison", "william-garrison", "faculty-pitt-cs-af900fe5", "William C. Garrison", "william-c-garrison"),
    ("Aakash Gautam", "aakash-gautam", "faculty-pitt-sci-6f929413"),
    ("Milos Hauskrecht", "milos-hauskrecht", "faculty-pitt-cs-19abea97"),
    ("Timothy Hoffman", "timothy-hoffman", "faculty-pitt-cs-fa134731", "Timothy L. Hoffman", "timothy-l-hoffman"),
    ("Emma Jordan", "emma-jordan", "faculty-pitt-cs-a32cf06c"),
    ("Sherif Khattab", "sherif-khattab", "faculty-pitt-cs-904e37e9"),
    ("Thumtongsak Kosiyatrkul", "thumtongsak-kosiyatrkul", "faculty-pitt-cs-a2c06c2d",
     "Thumrongsak Kosiyatrakul", "thumrongsak-kosiyatrkul"),
    ("Adriana Kovashka", "adriana-kovashka", "faculty-pitt-cs-4adac42c", "Adriana I. Kovashka", "adriana-i-kovashka"),
    ("Alexandros Labrinidis", "alexandros-labrinidis", "faculty-pitt-cs-3f53f93b"),
    ("John Lange", "john-lange", "faculty-pitt-cs-d11d4a3e", "John R. Lange", "john-r-lange"),
    ("Adam Lee", "adam-lee", "faculty-pitt-cs-3af1e2c9", "Adam J. Lee", "adam-j-lee"),
    ("Stephen Lee", "stephen-lee", "faculty-pitt-sci-754eb010"),
    ("Lorraine (Xiang) Li", "lorraine-xiang-li", "faculty-pitt-cs-5d973318"),
    ("Diane Litman", "diane-litman", "faculty-pitt-cs-4cb65ded", "Diane J. Litman", "diane-litman"),
    ("Junyu Liu", "junyu-liu", "faculty-pitt-sci-c98f98a1"),
    ("Daniel Mosse", "daniel-mosse", "faculty-pitt-cs-484b0709"),
    ("Nils Murrugarra-Llerena", "nils-murrugarra-llerena", "faculty-pitt-sci-68e4dc1f",
     "Nils Murrugarra Llerena", "nils-murrugarra-llerena"),
    ("Brian T. Nixon", "brian-t-nixon", "faculty-pitt-sci-7856039c"),
    ("Luis Oliveira", "luis-oliveira", "faculty-pitt-cs-dff77505", "Luis de Oliveira", "luis-de-oliveira"),
    ("Kirk Pruhs", "kirk-pruhs", "faculty-pitt-cs-74aa7171", "Kirk R. Pruhs", "kirk-r-pruhs"),
    ("John Ramirez", "john-ramirez", "faculty-pitt-cs-82cfa3dd", "John C. Ramirez", "john-c-ramirez"),
    ("Rob Rutenbar", "rob-rutenbar", "faculty-pitt-cs-51874e7c", "Rob A. Rutenbar", "rob-rutenbar"),
    ("Longfei Shangguan", "longfei-shangguan", "faculty-pitt-sci-1a259c98"),
    ("Ryan Shi", "ryan-shi", "faculty-pitt-cs-e643e15e"),
    ("Patrick Skeba", "patrick-skeba", "faculty-pitt-cs-ca9eac3e"),
    ("Xulong Tang", "xulong-tang", "faculty-pitt-cs-8e9a39d1"),
    ("Nadine von Frankenberg", "nadine-von-frankenberg", "faculty-pitt-sci-7f74cde0"),
    ("Erin Walker", "erin-walker", "faculty-pitt-cs-0a7196f1"),
    ("Youtao Zhang", "youtao-zhang", "faculty-pitt-cs-1e95f188"),
    ("Michael Miller Yoder", "michael-miller-yoder-0", "faculty-pitt-cs-1c364170",
     "Michael Miller Yoder", "michael-miller-yoder"),
):
    _register(*pair)


def reviewed_cs_appointment(row: dict) -> Appointment | None:
    if row.get("school") != "pitt" or row.get("source") != "pitt_faculty":
        return None
    if row.get("department") not in ("Department of Computer Science", "School of Computing and Information"):
        return None
    profile_url = (row.get("url") or "").strip().rstrip("/")
    return _PROFILES.get((profile_url, row.get("pi_name")))
