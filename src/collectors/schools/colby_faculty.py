"""Colby College faculty config (via the faculty_graph engine).

Colby is a top-tier US liberal arts college (~2,200 undergraduates, no graduate
school) in Waterville, Maine. Its entire public site sits behind Cloudflare,
which returns a 403 "Attention Required" interstitial to every plain HTTP
request (curl, requests) from datacenter IPs, so none of the live network
fetchers (scrape/api/algolia) can reach it on the weekly refresh. A headless
render DOES clear the interstitial, but the sole roster surface — the
college-wide People Directory at ``colby.edu/people/people-directory/`` — is a
Vue single-page app that ships its full ~1,130-person dataset as an
``external-items`` prop (name, business title, department, profile slug) and
paginates/filters it client-side with Fuse.js; the server-rendered DOM only
ever exposes the first 100 alphabetical rows, and there is no JSON/wp-json
endpoint that is not itself Cloudflare-walled.

The durable, deterministic solution is therefore the curated seed layer: the
full ``external-items`` payload was harvested once (2026-07-23, via a single
headless render that cleared Cloudflare), filtered to the ladder research
faculty, mapped to each professor's home academic department, and is embedded
below as ``faculty(...)`` entries. No render or network call happens on the
weekly refresh — the records are offline and Cloudflare-proof. Emails are not
published anywhere in the directory payload (the ``email`` field is null for
every person), so each record carries the professor's public People Directory
profile URL as the contact path; topics come from OpenAlex enrichment.

Ladder gate applied at harvest time: kept professorial + lecturer ranks and
genuine "Instructor of <discipline>" teaching faculty; dropped emeriti,
visiting, adjunct, postdoc/fellow appointments and the non-research staff that
share the directory (lab/laboratory instructors, applied-music instructors,
wellness/aerobics instructors, coaches, collaborative pianists). Cross-listed
professors (e.g. "Economics; Global Studies") were attributed to their primary
home department; the two "Colby College"-listed senior academics (the Provost,
a Jewish Studies chair) were reassigned to their teaching departments and the
President (an administrator) dropped.

Single source ("colby_faculty"); department rides each record, ids namespaced
by department short-code. Audience "unknown".

Deferred: non-academic units (athletics, libraries, IT, advancement, custodial,
facilities, admissions, dining) are staff directories, not research faculty,
and are intentionally excluded.
"""

from __future__ import annotations

from .. import faculty_graph
from ..faculty_graph import faculty

_DIR = "https://www.colby.edu/people/people-directory/"


def _dept(short: str, name: str, majors: list[str], people: list[dict]) -> dict:
    """A Colby academic department carrying its curated ladder-faculty seeds."""
    return {"short": short, "name": name, "majors": majors,
            "directory_url": _DIR, "faculty": people}


SCHOOL: dict = {
    "school_slug": "colby",
    "source": "colby_faculty",
    "organization": "Colby College",
    "location": "Waterville, ME",
    "id_prefix": "colby",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Colby College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences & Mathematics ----------------------------
        _dept("BIOL", "Department of Biology", ["Biology", "Neuroscience"], [
            faculty("Allison Barner", title="Clare Booth Luce Assistant Professor of Biology", url="https://www.colby.edu/people/people-directory/allison-barner/"),
            faculty("Andrea Tilden", title="The Leslie Brainerd Arey Associate Professor of Biosciences", url="https://www.colby.edu/people/people-directory/andrea-tilden/"),
            faculty("Andrea Wegrzynowicz", title="Assistant Professor of Biology", url="https://www.colby.edu/people/people-directory/andrea-wegrzynowicz/"),
            faculty("Anna Forsman", title="Assistant Professor of Biology", url="https://www.colby.edu/people/people-directory/anna-forsman/"),
            faculty("Catherine Bevier", title="Oak Professor of Biology", url="https://www.colby.edu/people/people-directory/catherine-bevier/"),
            faculty("Christina Cota", title="Assistant Professor of Biology", url="https://www.colby.edu/people/people-directory/christina-cota/"),
            faculty("Johanna van Oers", title="Lecturer in Biology", url="https://www.colby.edu/people/people-directory/johanna-van-oers/"),
            faculty("Josh Martin", title="Associate Professor of Biology", url="https://www.colby.edu/people/people-directory/josh-martin/"),
            faculty("Kristen Nolting", title="Assistant Professor of Biology", url="https://www.colby.edu/people/people-directory/kristen-nolting/"),
            faculty("Kyle Coblentz", title="Assistant Professor of Biology", url="https://www.colby.edu/people/people-directory/kyle-coblentz/"),
            faculty("Robert Augustine", title="Assistant Professor of Biology", url="https://www.colby.edu/people/people-directory/robert-augustine/"),
            faculty("Ron Peck", title="Associate Professor of Biology; Chair of Biology; Chair of Cell and Molecular Biology/Biochemistry", url="https://www.colby.edu/people/people-directory/ron-peck/"),
            faculty("Russell Johnson", title="Professor of Biology", url="https://www.colby.edu/people/people-directory/russell-johnson/"),
            faculty("Suegene Noh", title="Associate Professor of Biology; Natural Sciences Division Chair", url="https://www.colby.edu/people/people-directory/suegene-noh/"),
            faculty("Susan Childers", title="Lecturer in Biology", url="https://www.colby.edu/people/people-directory/susan-childers/"),
            faculty("Yee Mon Thu", title="Assistant Professor of Biology", url="https://www.colby.edu/people/people-directory/yee-mon-thu/"),
        ]),
        _dept("MATH", "Department of Mathematics", ["Mathematics"], [
            faculty("Casey Cavanaugh", title="Assistant Professor of Mathematics", url="https://www.colby.edu/people/people-directory/casey-cavanaugh/"),
            faculty("Evan Randles", title="Associate Professor of Mathematics; Chair of Mathematics", url="https://www.colby.edu/people/people-directory/evan-randles/"),
            faculty("Fernando Gouvea", title="Carter Professor of Mathematics; Associate Chair of Mathematics", url="https://www.colby.edu/people/people-directory/fernando-gouvea/"),
            faculty("Lei Xue", title="Assistant Professor of Mathematics", url="https://www.colby.edu/people/people-directory/lei-xue/"),
            faculty("Leo Livshits", title="Professor of Mathematics", url="https://www.colby.edu/people/people-directory/leo-livshits/"),
            faculty("Matt Jones", title="Assistant Professor of Mathematics", url="https://www.colby.edu/people/people-directory/matt-jones/"),
            faculty("Nora Youngs", title="Associate Professor of Mathematics", url="https://www.colby.edu/people/people-directory/nora-youngs/"),
            faculty("Scott Taylor", title="Professor of Mathematics", url="https://www.colby.edu/people/people-directory/scott-taylor/"),
            faculty("Stephanie Dodson", title="Assistant Professor of Mathematics", url="https://www.colby.edu/people/people-directory/stephanie-dodson/"),
            faculty("Tamar Friedmann", title="Assistant Professor of Mathematics", url="https://www.colby.edu/people/people-directory/tamar-friedmann/"),
            faculty("Tristan Phillips", title="Assistant Professor of Mathematics", url="https://www.colby.edu/people/people-directory/tristan-phillips/"),
            faculty("Zach Winkeler", title="Lecturer in Mathematics", url="https://www.colby.edu/people/people-directory/zach-winkeler/"),
        ]),
        _dept("CS", "Department of Computer Science", ["Computer Science"], [
            faculty("Allen Harper", title="Lecturer of Computer Science", url="https://www.colby.edu/people/people-directory/allen-harper/"),
            faculty("Eric Aaron", title="Associate Professor of Computer Science", url="https://www.colby.edu/people/people-directory/eric-aaron/"),
            faculty("Hannen Wolfe", title="Assistant Professor of Computer Science", url="https://www.colby.edu/people/people-directory/hannen-hannah-wolfe/"),
            faculty("Isaac Lage", title="Assistant Professor of Computer Science", url="https://www.colby.edu/people/people-directory/isaac-lage/"),
            faculty("Maximillian Bender", title="Assistant Professor of Computer Science", url="https://www.colby.edu/people/people-directory/maximillian-bender/"),
            faculty("Naser Al Madi", title="Associate Professor of Computer Science", url="https://www.colby.edu/people/people-directory/naser-al-madi/"),
            faculty("Oliver Layton", title="Associate Professor of Computer Science; Associate Chair of Computer Science", url="https://www.colby.edu/people/people-directory/oliver-layton/"),
            faculty("Stacy Doore", title="Clare Booth Luce Associate Professor of Computer Science", url="https://www.colby.edu/people/people-directory/stacy-doore/"),
            faculty("Stephanie Taylor", title="Professor of Computer Science", url="https://www.colby.edu/people/people-directory/stephanie-taylor/"),
            faculty("Tahiya Chowdhury", title="Clare Boothe Luce Assistant Professor of Computer Science", url="https://www.colby.edu/people/people-directory/tahiya-chowdhury/"),
            faculty("Ying Li", title="Associate Professor of Computer Science; Chair of Computer Science", url="https://www.colby.edu/people/people-directory/ying-li/"),
        ]),
        _dept("PSYC", "Department of Psychology", ["Psychology", "Neuroscience"], [
            faculty("Christopher Soto", title="Professor of Psychology", url="https://www.colby.edu/people/people-directory/christopher-soto/"),
            faculty("Claire Robertson", title="Assistant Professor of Psychology", url="https://www.colby.edu/people/people-directory/claire-robertson/"),
            faculty("Derek Huffman", title="Assistant Professor of Psychology", url="https://www.colby.edu/people/people-directory/derek-huffman/"),
            faculty("Elizabeth Seto", title="Associate Professor of Psychology", url="https://www.colby.edu/people/people-directory/elizabeth-seto/"),
            faculty("Erin Sheets", title="Professor of Psychology; Chair of Psychology", url="https://www.colby.edu/people/people-directory/erin-sheets/"),
            faculty("Jen Coane", title="Professor of Psychology; Associate Chair of Psychology", url="https://www.colby.edu/people/people-directory/jen-coane/"),
            faculty("Michael Sanders", title="Assistant Professor of Psychology", url="https://www.colby.edu/people/people-directory/michael-sanders/"),
            faculty("Rachel King", title="Assistant Professor of Psychology", url="https://www.colby.edu/people/people-directory/rachel-king/"),
            faculty("Tarja Raag", title="Associate Professor of Psychology", url="https://www.colby.edu/people/people-directory/tarja-raag/"),
            faculty("Veronica Romero", title="Assistant Professor of Psychology", url="https://www.colby.edu/people/people-directory/veronica-romero/"),
        ]),
        _dept("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"], [
            faculty("Dasan Thamattoor", title="J. Warren Merrill Professor in Chemistry and Natural History", url="https://www.colby.edu/people/people-directory/dasan-thamattoor/"),
            faculty("Greg Drozd", title="Associate Professor of Chemistry; Associate Chair of Chemistry", url="https://www.colby.edu/people/people-directory/greg-drozd/"),
            faculty("Jeff Katz", title="William R. Kenan, Jr. Professor of Chemistry", url="https://www.colby.edu/people/people-directory/jeff-katz/"),
            faculty("Julie Millard", title="The Dr. Gerald and Myra Dorros Professor of Chemistry", url="https://www.colby.edu/people/people-directory/julie-millard/"),
            faculty("Karena McKinney", title="Associate Professor of Chemistry; Chair of Chemistry", url="https://www.colby.edu/people/people-directory/karena-mckinney/"),
            faculty("Lindsey Madison", title="Associate Professor of Chemistry", url="https://www.colby.edu/people/people-directory/lindsey-madison/"),
            faculty("Rebecca Conry", title="Professor of Chemistry", url="https://www.colby.edu/people/people-directory/rebecca-conry/"),
            faculty("Reuben Hudson", title="Assistant Professor of Chemistry", url="https://www.colby.edu/people/people-directory/reuben-hudson/"),
            faculty("Whitney King", title="Dr. Frank and Theodora Miselis Professor of Chemistry", url="https://www.colby.edu/people/people-directory/whitney-king/"),
        ]),
        _dept("ENVS", "Environmental Studies Program", ["Environmental Studies", "Environmental Science", "Environmental Policy"], [
            faculty("Alejandra Ortiz", title="Assistant Professor of Environmental Studies", url="https://www.colby.edu/people/people-directory/alejandra-ortiz/"),
            faculty("Alison Bates", title="Associate Professor of Environmental Studies; Associate Chair of Environmental Studies", url="https://www.colby.edu/people/people-directory/alison-bates/"),
            faculty("Amanda Gallinat", title="Lecturer of Environmental Studies", url="https://www.colby.edu/people/people-directory/amanda-gallinat/"),
            faculty("Cait Cleaver", title="Assistant Professor of Environmental Studies", url="https://www.colby.edu/people/people-directory/cait-cleaver/"),
            faculty("Denise Bruesewitz", title="Provost, 2025-; Clara C. Piper Professor of Environmental Studies", url="https://www.colby.edu/people/people-directory/denise-bruesewitz/"),
            faculty("Diana Elhard", title="Assistant Professor of Environmental Studies", url="https://www.colby.edu/people/people-directory/diana-elhard/"),
            faculty("Gail Carlson", title="Associate Professor of Environmental Studies", url="https://www.colby.edu/people/people-directory/gail-carlson/"),
            faculty("Justin Becknell", title="Associate Professor of Environmental Studies; Chair of Environmental Studies", url="https://www.colby.edu/people/people-directory/justin-becknell/"),
            faculty("Philip Nyhus", title="Elizabeth and Lee Ainslie Professor of Environmental Studies; Interdisciplinary Studies Division Chair", url="https://www.colby.edu/people/people-directory/philip-nyhus/"),
        ]),
        _dept("PHYS", "Department of Physics and Astronomy", ["Physics", "Astronomy"], [
            faculty("Anna Reine", title="Assistant Professor of Physics", url="https://www.colby.edu/people/people-directory/anna-reine/"),
            faculty("Charles Conover", title="William A. Rogers Professor of Physics", url="https://www.colby.edu/people/people-directory/charles-conover/"),
            faculty("Dale Kocevski", title="Associate Professor of Physics and Astronomy; Chair of Physics and Astronomy", url="https://www.colby.edu/people/people-directory/dale-kocevski/"),
            faculty("Duncan Tate", title="Professor of Physics", url="https://www.colby.edu/people/people-directory/duncan-tate/"),
            faculty("Elizabeth McGrath", title="Associate Professor of Physics and Astronomy", url="https://www.colby.edu/people/people-directory/elizabeth-mcgrath/"),
            faculty("Jonathan McCoy", title="Associate Professor of Physics and Astronomy", url="https://www.colby.edu/people/people-directory/jonathan-mccoy/"),
            faculty("Robert Bluhm", title="Sunrise Professor of Physics", url="https://www.colby.edu/people/people-directory/robert-bluhm/"),
        ]),
        _dept("STAT", "Department of Statistics", ["Statistics"], [
            faculty("Annie Tang", title="Assistant Professor of Statistics", url="https://www.colby.edu/people/people-directory/annie-tang/"),
            faculty("Brianna Keefe-Oates", title="Lecturer in Public Health", url="https://www.colby.edu/people/people-directory/brianna-keefe-oates/"),
            faculty("Jerzy Wieczorek", title="Associate Professor of Statistics", url="https://www.colby.edu/people/people-directory/jerzy-wieczorek/"),
            faculty("Jim Scott", title="Associate Professor of Statistics; Chair of Statistics", url="https://www.colby.edu/people/people-directory/jim-scott/"),
            faculty("Liam O'Brien", title="Associate Provost for Academic Programs 2026 - , Charles A. Dana Professor of Statistics", url="https://www.colby.edu/people/people-directory/liam-obrien/"),
            faculty("Xi Ning", title="Assistant Professor of Statistics", url="https://www.colby.edu/people/people-directory/xi-ning/"),
        ]),
        _dept("EOAS", "Department of Earth, Oceans, and Atmospheric Science", ["Geology", "Earth Sciences"], [
            faculty("Bess Koffman", title="Associate Professor of Earth Sciences", url="https://www.colby.edu/people/people-directory/bess-koffman/"),
            faculty("Bill Sullivan", title="The Whipple-Coddington Professor of Earth Sciences", url="https://www.colby.edu/people/people-directory/bill-sullivan/"),
            faculty("Evan Dethier", title="Assistant Professor of Earth Sciences", url="https://www.colby.edu/people/people-directory/evan-dethier/"),
            faculty("Tasha Dunn", title="Associate Professor of Earth Sciences; Chair of Earth Sciences", url="https://www.colby.edu/people/people-directory/tasha-dunn/"),
        ]),
        _dept("STS", "Science, Technology and Society Program", ["Science, Technology and Society"], [
            faculty("Ashton Wesner", title="Assistant Professor of Science, Technology & Society", url="https://www.colby.edu/people/people-directory/ashton-wesner/"),
            faculty("Thom Klepach", title="Lecturer of Science, Technology and Society", url="https://www.colby.edu/people/people-directory/thom-klepach/"),
        ]),
        # ---- Social Sciences -------------------------------------------
        _dept("ECON", "Department of Economics", ["Economics"], [
            faculty("Andreas Waldkirch", title="The Mitchell Family Professor of Economics; Chair of Spanish", url="https://www.colby.edu/people/people-directory/andreas-waldkirch/"),
            faculty("Benjamin Scharadin", title="Assistant Professor of Economics", url="https://www.colby.edu/people/people-directory/benjamin-scharadin/"),
            faculty("Daniel LaFave", title="Professor of Economics", url="https://www.colby.edu/people/people-directory/daniel-lafave/"),
            faculty("Dave Findlay", title="Pugh Family Professor of Economics", url="https://www.colby.edu/people/people-directory/dave-findlay/"),
            faculty("Effie Karfaki", title="Assistant Professor of Economics", url="https://www.colby.edu/people/people-directory/effie-karfaki/"),
            faculty("Ekaterina Seregina", title="Douglas Assistant Professor of Economics and Finance", url="https://www.colby.edu/people/people-directory/ekaterina-seregina/"),
            faculty("Erin Giffin", title="Associate Professor of Economics", url="https://www.colby.edu/people/people-directory/erin-giffin/"),
            faculty("James Siodla", title="Associate Professor of Economics; Associate Chair of Economics", url="https://www.colby.edu/people/people-directory/james-siodla/"),
            faculty("Jen Meredith", title="Assistant Professor of Economics", url="https://www.colby.edu/people/people-directory/jen-meredith/"),
            faculty("Kathrin Ellieroth", title="Assistant Professor of Economics", url="https://www.colby.edu/people/people-directory/kathrin-ellieroth/"),
            faculty("Linwood Downs", title="Assistant Professor of Economics", url="https://www.colby.edu/people/people-directory/linwood-downs/"),
            faculty("Michael Donihue", title="Herbert E. Wadsworth 1892 Professor of Economics; Associate Vice President for Academic Affairs and Associate Dean of Faculty, 2008-2010", url="https://www.colby.edu/people/people-directory/michael-donihue/"),
            faculty("Patrice Franko", title="Grossman Professor of Economics", url="https://www.colby.edu/people/people-directory/patrice-franko/"),
            faculty("Raymond Caraher", title="Assistant Professor of Economics", url="https://www.colby.edu/people/people-directory/raymond-caraher/"),
            faculty("Rob Lester", title="Associate Professor of Economics", url="https://www.colby.edu/people/people-directory/rob-lester/"),
            faculty("Samara Gunter", title="Professor of Economics; Chair of Economics", url="https://www.colby.edu/people/people-directory/samara-gunter/"),
            faculty("Sanval Nasim", title="Assistant Professor of Economics", url="https://www.colby.edu/people/people-directory/sanval-nasim/"),
            faculty("Stephanie Owen", title="Assistant Professor of Economics", url="https://www.colby.edu/people/people-directory/stephanie-owen/"),
            faculty("Tim Hubbard", title="Francis F. Bartlett and Ruth K. Bartlett Professor of Economics", url="https://www.colby.edu/people/people-directory/tim-hubbard/"),
            faculty("Yang Fan", title="Todger Anderson Associate Professor of Investing and Behavioral Economics", url="https://www.colby.edu/people/people-directory/yang-fan/"),
        ]),
        _dept("GOVT", "Department of Government", ["Government", "Political Science"], [
            faculty("Carrie LeVan", title="The Montgoris Associate Professor of Government", url="https://www.colby.edu/people/people-directory/carrie-levan/"),
            faculty("Dan Shea", title="The Marson-Moller-McNulty Professor of Government", url="https://www.colby.edu/people/people-directory/dan-shea/"),
            faculty("Gloria Xiong", title="Assistant Professor of Government", url="https://www.colby.edu/people/people-directory/gloria-xiong/"),
            faculty("Guilain Denoeux", title="Professor of Government", url="https://www.colby.edu/people/people-directory/guilain-denoeux/"),
            faculty("Holly Dunn", title="Assistant Professor of Government", url="https://www.colby.edu/people/people-directory/holly-dunn/"),
            faculty("Jennifer Yoder", title="Robert E. Diamond Professor of Government", url="https://www.colby.edu/people/people-directory/jennifer-yoder/"),
            faculty("Joseph Reisert", title="Harriet S. Wiswell and George C. Wiswell Jr. Professor of American Constitutional Law; Social Sciences Division Chair; Chair of Government", url="https://www.colby.edu/people/people-directory/joseph-reisert/"),
            faculty("Ken Rodman", title="William R. Cotter Distinguished Teaching Professor of Government", url="https://www.colby.edu/people/people-directory/ken-rodman/"),
            faculty("Lindsay Mayka", title="Associate Professor of Government", url="https://www.colby.edu/people/people-directory/lindsay-mayka/"),
            faculty("Nazli Konya", title="Assistant Professor of Government", url="https://www.colby.edu/people/people-directory/nazli-konya/"),
            faculty("Nicholas Jacobs", title="Goldfarb Family Distinguished Associate Professor of American Government", url="https://www.colby.edu/people/people-directory/nicholas-jacobs/"),
            faculty("Vivian Ferrillo", title="Assistant Professor of Government", url="https://www.colby.edu/people/people-directory/vivian-ferrillo/"),
        ]),
        _dept("ANTH", "Department of Anthropology", ["Anthropology"], [
            faculty("Britt Halvorson", title="Associate Professor of Anthropology; Chair of Anthropology", url="https://www.colby.edu/people/people-directory/britt-halvorson/"),
            faculty("Catherine Besteman", title="Francis F. Bartlett and Ruth K. Bartlett Professor of Anthropology", url="https://www.colby.edu/people/people-directory/catherine-besteman/"),
            faculty("Chandra Bhimull", title="The Audrey Wade Hittinger Katz and Sheldon Toby Katz Professor for Distinguished Teaching in Anthropology and African-American Studies", url="https://www.colby.edu/people/people-directory/chandra-bhimull/"),
            faculty("Farah Qureshi", title="Assistant Professor of Anthropology", url="https://www.colby.edu/people/people-directory/farah-qureshi/"),
            faculty("M. Suzanne Menair", title="Lecturer of Anthropology", url="https://www.colby.edu/people/people-directory/m-suzanne-menair/"),
            faculty("Mehrdad Babadi", title="Assistant Professor of Anthropology", url="https://www.colby.edu/people/people-directory/mehrdad-babadi/"),
            faculty("Winifred Tate", title="Professor of Anthropology", url="https://www.colby.edu/people/people-directory/winifred-tate/"),
        ]),
        _dept("SOC", "Department of Sociology", ["Sociology"], [
            faculty("Christel Kesler", title="Associate Professor of Sociology; Chair of Sociology", url="https://www.colby.edu/people/people-directory/christel-kesler/"),
            faculty("Damon Mayrl", title="Charles A. Dana Professor of Sociology", url="https://www.colby.edu/people/people-directory/damon-mayrl/"),
            faculty("Luis Tenorio", title="Assistant Professor of Sociology", url="https://www.colby.edu/people/people-directory/luis-tenorio/"),
            faculty("Neil Gross", title="Charles A. Dana Professor of Sociology", url="https://www.colby.edu/people/people-directory/neil-gross/"),
            faculty("Nicole Denier", title="Associate Professor of Sociology", url="https://www.colby.edu/people/people-directory/nicole-denier/"),
        ]),
        _dept("EDUC", "Education Program", ["Education"], [
            faculty("Adam Howard", title="Charles A. Dana Professor of Education", url="https://www.colby.edu/people/people-directory/adam-howard/"),
            faculty("Lauren Yoshizawa", title="Assistant Professor of Education; Chair of Education", url="https://www.colby.edu/people/people-directory/lauren-yoshizawa/"),
            faculty("Pei Pei Liu", title="Assistant Professor of Education", url="https://www.colby.edu/people/people-directory/pei-pei-liu/"),
            faculty("Sherry Pineau Brown", title="Lecturer in Education/Coordinator of Teacher Education", url="https://www.colby.edu/people/people-directory/sherry-pineau-brown/"),
        ]),
        _dept("GLBL", "Global Studies Program", ["Global Studies"], [
            faculty("Maple Razsa", title="Professor of Global Studies; Chair of Global Studies", url="https://www.colby.edu/people/people-directory/maple-razsa/"),
            faculty("Nadia El-Shaarawi", title="Associate Professor of Global Studies", url="https://www.colby.edu/people/people-directory/nadia-el-shaarawi/"),
            faculty("Quỳnh N. Phạm", title="Assistant Professor of Global Studies", url="https://www.colby.edu/people/people-directory/quynh-n-pham/"),
        ]),
        _dept("WGSS", "Women's, Gender, and Sexuality Studies Program", ["Women's, Gender, and Sexuality Studies"], [
            faculty("Jay Sibara", title="Associate Professor of Women's, Gender, and Sexuality Studies", url="https://www.colby.edu/people/people-directory/jay-sibara/"),
            faculty("Laura Sachiko Fugikawa", title="Assistant Professor of American Studies and Women's Gender and Sexuality Studies", url="https://www.colby.edu/people/people-directory/laura-sachiko-fugikawa/"),
            faculty("Sonja Thomas", title="Professor of Women's, Gender, and Sexuality Studies", url="https://www.colby.edu/people/people-directory/sonja-thomas/"),
        ]),
        _dept("AMST", "American Studies Program", ["American Studies"], [
            faculty("Ben Lisle", title="Associate Professor of American Studies; Chair of American Studies", url="https://www.colby.edu/people/people-directory/ben-lisle/"),
            faculty("Laura Saltz", title="Associate Professor of American Studies", url="https://www.colby.edu/people/people-directory/laura-saltz/"),
        ]),
        _dept("AAST", "African American Studies Program", ["African American Studies"], [
            faculty("Sonya Donaldson", title="Assistant Professor of African-American Studies", url="https://www.colby.edu/people/people-directory/sonya-donaldson/"),
        ]),
        # ---- Humanities ------------------------------------------------
        _dept("ENGL", "Department of English", ["English", "Creative Writing"], [
            faculty("Aaron Hanlon", title="NEH/Class of 1940 Distinguished Associate Professor of English; Co-Chair of English", url="https://www.colby.edu/people/people-directory/aaron-hanlon/"),
            faculty("Adrian Blevins", title="Professor of English", url="https://www.colby.edu/people/people-directory/adrian-blevins/"),
            faculty("Arisa White", title="Associate Professor of English (Creative Writing); Creative Writing Director", url="https://www.colby.edu/people/people-directory/arisa-white/"),
            faculty("Chris Walker", title="Assistant Professor of English", url="https://www.colby.edu/people/people-directory/chris-walker/"),
            faculty("Debra Spark", title="Zacamy Professor of English", url="https://www.colby.edu/people/people-directory/debra-spark/"),
            faculty("Dyani Taff", title="Assistant Professor of English", url="https://www.colby.edu/people/people-directory/dyani-taff/"),
            faculty("Elizabeth Sagaser", title="Associate Professor of English", url="https://www.colby.edu/people/people-directory/elizabeth-sagaser/"),
            faculty("Katherine Stubbs", title="Lee Family Associate Professor of English; Co-Chair of Music", url="https://www.colby.edu/people/people-directory/katherine-stubbs/"),
            faculty("Megan Cook", title="Arthur Jeremiah Roberts Professor of Literature", url="https://www.colby.edu/people/people-directory/megan-cook/"),
            faculty("Mohammad Shabangu", title="Assistant Professor of English", url="https://www.colby.edu/people/people-directory/mohammad-shabangu/"),
            faculty("Nicholas Silcox", title="Assistant Professor of English", url="https://www.colby.edu/people/people-directory/nicholas-silcox/"),
            faculty("Onnesha Roychoudhuri", title="Assistant Professor of English", url="https://www.colby.edu/people/people-directory/onnesha-roychoudhuri/"),
            faculty("Sam Plasencia", title="Assistant Professor of English", url="https://www.colby.edu/people/people-directory/sam-plasencia/"),
            faculty("Sarah Braunstein", title="Associate Professor of English (Creative Writing); Co-Chair of English", url="https://www.colby.edu/people/people-directory/sarah-braunstein/"),
        ]),
        _dept("SPAN", "Department of Spanish", ["Spanish", "Latin American Studies"], [
            faculty("Ana Almeyda-Cohen", title="Assistant Professor of Spanish", url="https://www.colby.edu/people/people-directory/ana-almeyda-cohen/"),
            faculty("Anna Tybinko", title="Assistant Professor of Spanish", url="https://www.colby.edu/people/people-directory/anna-tybinko/"),
            faculty("Ben Fallaw", title="Professor of Latin American Studies", url="https://www.colby.edu/people/people-directory/ben-fallaw/"),
            faculty("Brett White", title="Associate Professor of Spanish", url="https://www.colby.edu/people/people-directory/brett-white/"),
            faculty("Damaris Mayans", title="Assistant Professor of Spanish", url="https://www.colby.edu/people/people-directory/damaris-mayans/"),
            faculty("Dean Allbritton", title="Professor of Spanish", url="https://www.colby.edu/people/people-directory/dean-allbritton/"),
            faculty("Hector Ramos Flores", title="Associate Professor of Spanish; Chair of Latin American Studies; Associate Chair of Spanish", url="https://www.colby.edu/people/people-directory/hector-ramos-flores/"),
            faculty("Lola Bollo-Panadero", title="Associate Professor of Spanish", url="https://www.colby.edu/people/people-directory/lola-bollo-panadero/"),
            faculty("Luis Millones", title="The Allen Family Professor of Latin American Literature", url="https://www.colby.edu/people/people-directory/luis-millones/"),
            faculty("Sandra Bernal Heredia", title="Assistant Professor of Spanish", url="https://www.colby.edu/people/people-directory/sandra-bernal-heredia/"),
            faculty("Tiffany Miller", title="Assistant Professor of Spanish", url="https://www.colby.edu/people/people-directory/tiffany-miller/"),
        ]),
        _dept("HIST", "Department of History", ["History"], [
            faculty("Arnout van der Meer", title="Associate Professor of History", url="https://www.colby.edu/people/people-directory/arnout-van-der-meer/"),
            faculty("Danae Jacobson", title="Assistant Professor of History", url="https://www.colby.edu/people/people-directory/danae-jacobson/"),
            faculty("Inga Diederich", title="Assistant Professor of History", url="https://www.colby.edu/people/people-directory/inga-diederich/"),
            faculty("John Turner", title="Dean of Faculty 2025 - ; Associate Professor of History", url="https://www.colby.edu/people/people-directory/john-turner/"),
            faculty("Kelly Brignac", title="Assistant Professor of History", url="https://www.colby.edu/people/people-directory/kelly-brignac/"),
            faculty("Larissa Taylor", title="Professor of History", url="https://www.colby.edu/people/people-directory/larissa-taylor/"),
            faculty("Raffael Scheck", title="The John J. and Cornelia V. Gibson Professor of History; Associate Chair of History", url="https://www.colby.edu/people/people-directory/raffael-scheck/"),
            faculty("Rob Weisbrot", title="Christian A. Johnson Distinguished Teaching Professor of History", url="https://www.colby.edu/people/people-directory/rob-weisbrot/"),
            faculty("Sarah Duff", title="Associate Professor of History; Chair of History", url="https://www.colby.edu/people/people-directory/sarah-duff/"),
            faculty("Zoe Shan Lin", title="Assistant Professor of History", url="https://www.colby.edu/people/people-directory/zoe-shan-lin/"),
        ]),
        _dept("FRIT", "Department of French and Italian", ["French", "Italian"], [
            faculty("Adrianna Paliyenko", title="The Arnold Bernhard Professor of Arts and Humanities", url="https://www.colby.edu/people/people-directory/adrianna-paliyenko/"),
            faculty("Audrey Brunetaux", title="Associate Professor of French", url="https://www.colby.edu/people/people-directory/audrey-brunetaux/"),
            faculty("Benedicte Mauguiere", title="Professor of French", url="https://www.colby.edu/people/people-directory/benedicte-mauguiere/"),
            faculty("Flavien Falantin", title="Assistant Professor of French", url="https://www.colby.edu/people/people-directory/flavien-falantin/"),
            faculty("Gianluca Rizzo", title="Paul D. and Marilyn Paganucci Associate Professor of Italian Language and Literature", url="https://www.colby.edu/people/people-directory/gianluca-rizzo/"),
            faculty("Giovanni Miglianti", title="Assistant Professor of Italian", url="https://www.colby.edu/people/people-directory/giovanni-miglianti/"),
            faculty("Mouhamedoul Niang", title="Professor of French", url="https://www.colby.edu/people/people-directory/mouhamedoul-niang/"),
            faculty("Valerie Dionne", title="Professor of French and Italian; Chair of French and Italian", url="https://www.colby.edu/people/people-directory/valerie-dionne/"),
        ]),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"], [
            faculty("Ben Baker", title="Assistant Professor of Philosophy", url="https://www.colby.edu/people/people-directory/ben-baker/"),
            faculty("Dan Cohen", title="Professor of Philosophy", url="https://www.colby.edu/people/people-directory/dan-cohen/"),
            faculty("Elizabeth Hill", title="Assistant Professor of Philosophy", url="https://www.colby.edu/people/people-directory/elizabeth-hill/"),
            faculty("Jim Behuniak", title="William R. Kenan, Jr. Professor of Philosophy", url="https://www.colby.edu/people/people-directory/jim-behuniak/"),
            faculty("Keith Peterson", title="Professor of Philosophy; Chair of Philosophy", url="https://www.colby.edu/people/people-directory/keith-peterson/"),
            faculty("Lydia Moland", title="John D. and Catherine T. MacArthur Professor of Philosophy", url="https://www.colby.edu/people/people-directory/lydia-moland/"),
        ]),
        _dept("EALC", "Department of East Asian Languages and Cultures", ["Chinese", "Japanese", "East Asian Studies"], [
            faculty("Ankeney Weitz", title="Ziskind Professor of East Asian Languages and Cultures and Art", url="https://www.colby.edu/people/people-directory/ankeney-weitz/"),
            faculty("Fang Wang", title="Assistant Professor of East Asian Languages and Cultures", url="https://www.colby.edu/people/people-directory/fang-wang/"),
            faculty("Hong Zhang", title="Professor of East Asian Languages and Cultures", url="https://www.colby.edu/people/people-directory/hong-zhang/"),
            faculty("Kim Besio", title="Oak Professor of East Asian Languages and Cultures; Chair of East Asian Languages and Cultures", url="https://www.colby.edu/people/people-directory/kim-besio/"),
            faculty("Laura Nuffer", title="Assistant Professor of East Asian Languages and Cultures", url="https://www.colby.edu/people/people-directory/laura-nuffer/"),
            faculty("Rio Katayama", title="Assistant Professor of East Asian Languages and Cultures", url="https://www.colby.edu/people/people-directory/rio-katayama/"),
        ]),
        _dept("WRIT", "Writing Department", ["Writing"], [
            faculty("Chaoran Wang", title="Multilingual Writing Specialist and Assistant Professor of Writing", url="https://www.colby.edu/people/people-directory/chaoran-wang/"),
            faculty("Elisabeth Fairfield", title="Distinguished Senior Lecturer of Writing", url="https://www.colby.edu/people/people-directory/elisabeth-fairfield/"),
            faculty("Elizabeth Ketner", title="Senior Lecturer of Writing", url="https://www.colby.edu/people/people-directory/elizabeth-ketner/"),
            faculty("Ghada Gherwash", title="Assistant Professor and Director of the Farnham Writers' Center", url="https://www.colby.edu/people/people-directory/ghada-gherwash/"),
            faculty("Stacey Sheriff", title="Associate Professor of Writing", url="https://www.colby.edu/people/people-directory/stacey-sheriff/"),
        ]),
        _dept("CLAS", "Department of Classics", ["Classics", "Latin", "Greek"], [
            faculty("James Taylor", title="Assistant Professor of Classics", url="https://www.colby.edu/people/people-directory/james-taylor/"),
            faculty("Kassandra Miller", title="Assistant Professor of Classics", url="https://www.colby.edu/people/people-directory/kassandra-miller/"),
            faculty("Kerill O'Neill", title="Julian D. Taylor Professor of Classics; Chair of Classics", url="https://www.colby.edu/people/people-directory/kerill-oneill/"),
            faculty("Rebecca Frank", title="Assistant Professor of Classics", url="https://www.colby.edu/people/people-directory/rebecca-frank/"),
        ]),
        _dept("GERU", "Department of German and Russian", ["German", "Russian"], [
            faculty("Alicia Ellis", title="Associate Professor of German; Chair of African-American Studies", url="https://www.colby.edu/people/people-directory/alicia-ellis/"),
            faculty("Arne Koch", title="Associate Professor of German and Russian; Chair of German and Russian", url="https://www.colby.edu/people/people-directory/arne-koch/"),
            faculty("Elena Monastireva-Ansdell", title="Associate Professor of Russian", url="https://www.colby.edu/people/people-directory/elena-monastireva-ansdell/"),
            faculty("Melissa Miller", title="Assistant Professor of Russian", url="https://www.colby.edu/people/people-directory/melissa-miller/"),
        ]),
        _dept("RELG", "Department of Religious Studies", ["Religious Studies"], [
            faculty("Joshua Urich", title="Assistant Professor of Religious Studies", url="https://www.colby.edu/people/people-directory/joshua-urich/"),
            faculty("Kerry Sonia", title="Assistant Professor of Religious Studies", url="https://www.colby.edu/people/people-directory/kerry-sonia/"),
            faculty("Nikky Singh", title="Crawford Family Professor of Religion; Chair of Religious Studies", url="https://www.colby.edu/people/people-directory/nikky-singh/"),
        ]),
        _dept("JEWS", "Jewish Studies Program", ["Jewish Studies"], [
            faculty("David Freidenreich", title="Pulver Family Professor of Jewish Studies; Chair of Jewish Studies", url="https://www.colby.edu/people/people-directory/david-freidenreich/"),
            faculty("Lauren Cohen Fisher", title="Director of Jewish Student Life and Lecturer in Jewish Studies", url="https://www.colby.edu/people/people-directory/lauren-cohen-fisher/"),
            faculty("Rachel Isaacs", title="Dorothy \"Bibby\" Levine Alfond Assistant Professor of Jewish Studies", url="https://www.colby.edu/people/people-directory/rachel-isaacs/"),
        ]),
        # ---- Arts ------------------------------------------------------
        _dept("ART", "Department of Art", ["Art", "Art History", "Studio Art"], [
            faculty("Amanda Lilleston", title="Assistant Professor of Art", url="https://www.colby.edu/people/people-directory/amanda-lilleston/"),
            faculty("Bevin Engman", title="Professor of Art", url="https://www.colby.edu/people/people-directory/bevin-engman/"),
            faculty("Bradley Borthwick", title="Associate Professor of Art; Interim Director of the Global Entry Semester program in Dijon, France", url="https://www.colby.edu/people/people-directory/bradley-borthwick/"),
            faculty("Daniel Harkett", title="Associate Professor of Art; Chair of Art", url="https://www.colby.edu/people/people-directory/daniel-harkett/"),
            faculty("Gary Green", title="Professor of Art", url="https://www.colby.edu/people/people-directory/gary-green/"),
            faculty("Marta Ameri", title="Associate Professor of Art; Division Chair of Humanities", url="https://www.colby.edu/people/people-directory/marta-ameri/"),
            faculty("Taka Suzuki", title="Assistant Professor of Art", url="https://www.colby.edu/people/people-directory/taka-suzuki/"),
            faculty("Tanya Sheehan", title="James M. Gillespie Professor of Science, Technology, and Society; Chair of Science, Technology and Society", url="https://www.colby.edu/people/people-directory/tanya-sheehan/"),
            faculty("Véronique Plesch", title="Ellerton M. and Edith K. Jette Professor of Art", url="https://www.colby.edu/people/people-directory/veronique-plesch/"),
        ]),
        _dept("PTD", "Department of Performance, Theater, and Dance", ["Theater and Dance", "Performance"], [
            faculty("Annie Kloppenberg", title="Professor of Performance, Theater & Dance", url="https://www.colby.edu/people/people-directory/annie-kloppenberg/"),
            faculty("Bess Welden", title="Senior Lecturer of Performance, Theater and Dance", url="https://www.colby.edu/people/people-directory/bess-welden/"),
            faculty("Gwyneth Shanks", title="Assistant Professor of Performance, Theater and Dance", url="https://www.colby.edu/people/people-directory/gwyneth-shanks/"),
            faculty("Jim Thurston", title="Associate Professor of Performance, Theater and Dance", url="https://www.colby.edu/people/people-directory/jim-thurston/"),
            faculty("Matthew Cumbie", title="Assistant Professor of Performance, Theater, and Dance", url="https://www.colby.edu/people/people-directory/matthew-cumbie/"),
        ]),
        _dept("MUS", "Department of Music", ["Music"], [
            faculty("Emmalouise St. Amand", title="Assistant Professor of Music", url="https://www.colby.edu/people/people-directory/emmalouise-st-amand/"),
            faculty("José Martínez", title="Assistant Professor of Music", url="https://www.colby.edu/people/people-directory/jose-martinez/"),
            faculty("Natalie Zelensky", title="Associate Professor of Music", url="https://www.colby.edu/people/people-directory/natalie-zelensky/"),
            faculty("Yuri Funahashi", title="Associate Professor of Music", url="https://www.colby.edu/people/people-directory/yuri-funahashi/"),
        ]),
        _dept("CINE", "Cinema Studies Program", ["Cinema Studies"], [
            faculty("Erin Murphy", title="Instructor of Cinema Studies", url="https://www.colby.edu/people/people-directory/erin-murphy/"),
            faculty("Seth Kim", title="Assistant Professor of Cinema Studies", url="https://www.colby.edu/people/people-directory/seth-kim/"),
            faculty("Steve Wurtzler", title="Associate Professor of Cinema Studies; Chair of Cinema Studies", url="https://www.colby.edu/people/people-directory/steve-wurtzler/"),
        ]),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
