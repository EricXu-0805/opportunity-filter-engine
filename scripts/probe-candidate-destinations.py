"""One read per distinct listed URL, with exact sample IDs from the 2026-11-16 audit."""
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urldefrag, urlsplit
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup


def words(value):
    return re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", value).encode("ascii","ignore").decode().lower())

def read(url):
    try:
        with urlopen(Request(url, headers={"User-Agent":"opportunity-filter-engine/official-faculty-check"}), timeout=12) as response:
            soup = BeautifulSoup(response.read(3_000_000), "html.parser")
            for tag in soup.find_all(["script","style"]):
                tag.decompose()
            return response.status, response.url, " ".join(words(soup.get_text(" ", strip=True))), [t.get_text(" ",strip=True)[:180] for t in soup.select("h1, title")[:6]]
    except HTTPError as exc:
        return exc.code, exc.url, "", []
    except (TimeoutError, OSError, ValueError) as exc:
        return type(exc).__name__, url, "", []


DESTINATIONS = {"osu_profile":"https://agsafety.osu.edu/people/dee-jepsen-phd","osu_roster":"https://agsafety.osu.edu/people","sbu_paola":"https://researchconnect.stonybrook.edu/en/persons/paola-cascante-bonilla/","sbu_paola_cs":"https://paolacascante.com/","sbu_ting":"https://alps-lab.github.io/","tamu":"https://bush.tamu.edu/directory/john-schuessler/","umd_ber":"https://www-math.umd.edu/signage-directory-faculty/2025-sberhanu.html","umd_beise":"https://umdphysics.umd.edu/directory/faculty/emeritus/beise.html","umd_beise_roster":"https://umdphysics.umd.edu/people/faculty/emeritus.html"}
EXPECTED = {"osu_profile":"jepsen","osu_roster":"jepsen","sbu_paola":"cascante","sbu_paola_cs":"cascante","sbu_ting":"ting wang","tamu":"schuessler","umd_ber":"berhanu","umd_beise":"beise","umd_beise_roster":"beise"}
for label, url in DESTINATIONS.items():
    code, final, page, headings = read(url)
    name = EXPECTED[label]
    print(label, code, "name", name in page, "profile_heading", any(name in " ".join(words(h)) for h in headings), "emerita_appears", "professor emerita" in page, flush=True)
