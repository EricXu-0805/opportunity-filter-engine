"""Wesleyan University faculty config (via the faculty_graph engine).

Wesleyan is a highly selective liberal-arts university (~3,000 undergraduates
plus small graduate programs) in Middletown, CT, with unusual research depth
for a LAC — active laboratory science across Biology, Chemistry, Molecular
Biology & Biochemistry, Physics, Astronomy (the historic Van Vleck
Observatory) and Earth & Environmental Sciences, alongside nationally known
Film, Music, and East Asian Studies programs.

Data source (live-verified 2026-07-22, no WAF, no render mode anywhere):
Wesleyan runs ONE central people directory. Every department's "People" page
is a thin client-side shell that fetches from a shared endpoint —

    https://www.wesleyan.edu/about/directory/directory-loader.php
        ?title=professor&type=faculty&searchtype=people

— which returns the entire ladder faculty of the university as clean JSON
(``name``, ``positions`` list, ``email``, ``id``, ``department_classes``). A
single request covers all departments with 100%% inline institutional email.

The endpoint groups its records two levels deep (``{items: {A: [...], ...}}``
for the university-wide feed, ``{items: {chairs: [...], faculty: [...],
affiliated: [...]}}`` per department), a shape none of the faculty_graph
network fetchers can flatten (``json_dir`` unwraps only one level). Rather than
add engine machinery, this module ships the directory as a **curated seed
layer**: every record below was harvested verbatim from the live API, bucketed
into its home department via the ``department_classes`` tag, and filtered to
the cold-emailable research faculty.

Ladder gate applied at harvest (the curated-layer equivalent of a
``ladder_filter``): keep records whose primary position carries a professorial
/ lecturer / instructor / curator rank; drop Emeritus/Emerita, Visiting,
Adjunct, Artist-in-Residence, and Physical-Education (athletics) appointments,
and the separate ``type=staff`` roster entirely. Each professor's ``url`` is
the stable central-directory profile (``/about/directory/profile.html?id=<id>``);
``directory_url`` is the department's own People/home page.

Single source ("wesleyan_faculty"); department rides each record, ids
namespaced by department short-code. Audience "unknown". The engine's
per-school email/id dedup collapses the faculty who are jointly appointed
across departments (e.g. a Biology professor also in Neuroscience & Behavior or
the College of Integrative Sciences) to a single home-department record.

Deferred: the ~7 small administrative centers with no dedicated academic
roster (Academic Affairs, Continuing Studies, the Patricelli Center, the
Digital Design Commons, the Fries Center for Global Studies) — their listed
people are cross-appointed from the academic departments already captured here.
Research keywords are intentionally absent: the directory API carries no
per-person research field, and there is no scrapeable static profile to enrich
from, so records ship with clean rank titles and contact emails only.
"""

from __future__ import annotations

from .. import faculty_graph
from ..faculty_graph import faculty


def _dept(short: str, name: str, majors: list[str], directory_url: str,
          people: list[dict]) -> dict:
    """A Wesleyan department carrying a curated faculty seed list harvested
    from the central directory API (live-verified 2026-07-22)."""
    return {"short": short, "name": name, "majors": majors,
            "directory_url": directory_url, "faculty": people}


SCHOOL: dict = {
    "school_slug": "wesleyan",
    "source": "wesleyan_faculty",
    "organization": "Wesleyan University",
    "location": "Middletown, CT",
    "id_prefix": "wesleyan",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Wesleyan University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Natural Sciences & Mathematics ------------------------------
        _dept("ASTR", "Department of Astronomy", ["Astronomy"],
               "https://www.wesleyan.edu/academics/departments/astronomy/people.html", [
            faculty("Meredith Hughes", title="Professor of Astronomy", url="https://www.wesleyan.edu/about/directory/profile.html?id=amhughes", email="amhughes@wesleyan.edu"),
            faculty("Edward Moran", title="Professor of Astronomy", url="https://www.wesleyan.edu/about/directory/profile.html?id=emoran", email="emoran@wesleyan.edu"),
            faculty("Seth Redfield", title="Professor of Astronomy", url="https://www.wesleyan.edu/about/directory/profile.html?id=sredfield", email="sredfield@wesleyan.edu"),
            faculty("Sarah Wellons", title="Assistant Professor of Astronomy", url="https://www.wesleyan.edu/about/directory/profile.html?id=swellons", email="swellons@wesleyan.edu"),
        ]),
        _dept("BIOL", "Department of Biology", ["Biology"],
               "https://www.wesleyan.edu/bio/", [
            faculty("Gloster Aaron", title="Associate Professor of Biology", url="https://www.wesleyan.edu/about/directory/profile.html?id=gaaron", email="gaaron@wesleyan.edu"),
            faculty("Phil Arevalo", title="Assistant Professor of the Practice in Biology and CIS", url="https://www.wesleyan.edu/about/directory/profile.html?id=parevalo", email="parevalo@wesleyan.edu"),
            faculty("Frederick Cohan", title="Professor of Biology", url="https://www.wesleyan.edu/about/directory/profile.html?id=fcohan", email="fcohan@wesleyan.edu"),
            faculty("Joseph Coolon", title="Associate Professor of Biology", url="https://www.wesleyan.edu/about/directory/profile.html?id=jcoolon", email="jcoolon@wesleyan.edu"),
            faculty("Ni Feng", title="Assistant Professor of Biology", url="https://www.wesleyan.edu/about/directory/profile.html?id=nfeng", email="nfeng@wesleyan.edu"),
            faculty("Ruth Johnson", title="Associate Professor of Biology", url="https://www.wesleyan.edu/about/directory/profile.html?id=rijohnson", email="rijohnson@wesleyan.edu"),
            faculty("Laverne Melon", title="Assistant Professor of Biology", url="https://www.wesleyan.edu/about/directory/profile.html?id=lmelon", email="lmelon@wesleyan.edu"),
            faculty("Jennifer Mitchel", title="Assistant Professor of Biology", url="https://www.wesleyan.edu/about/directory/profile.html?id=jmitchel", email="jmitchel@wesleyan.edu"),
            faculty("Michelle Murolo", title="Professor of the Practice in Biology", url="https://www.wesleyan.edu/about/directory/profile.html?id=mmurolo", email="mmurolo@wesleyan.edu"),
            faculty("Michael Singer", title="Professor of Biology", url="https://www.wesleyan.edu/about/directory/profile.html?id=msinger", email="msinger@wesleyan.edu"),
            faculty("Sonia Sultan", title="Professor of Biology", url="https://www.wesleyan.edu/about/directory/profile.html?id=sesultan", email="sesultan@wesleyan.edu"),
            faculty("Boris Tezak", title="Assistant Professor of Biology", url="https://www.wesleyan.edu/about/directory/profile.html?id=btezak", email="btezak@wesleyan.edu"),
            faculty("Michael Weir", title="Professor of Biology", url="https://www.wesleyan.edu/about/directory/profile.html?id=mweir", email="mweir@wesleyan.edu"),
        ]),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"],
               "https://www.wesleyan.edu/chem/faculty-and-staff/index.html", [
            faculty("Michael Calter", title="Professor of Chemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=mcalter", email="mcalter@wesleyan.edu"),
            faculty("Michelle Chen", title="Assistant Professor of Chemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=mchen02", email="mchen02@wesleyan.edu"),
            faculty("Carla Coste Sanchez", title="Assistant Professor of the Practice in Chemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=ccostesanch", email="ccostesanch@wesleyan.edu"),
            faculty("Benjamin Elling", title="Assistant Professor of Chemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=belling", email="belling@wesleyan.edu"),
            faculty("Michael Frisch", title="Professor of Chemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=mfrisch", email="mfrisch@wesleyan.edu"),
            faculty("Natalia Gonzalez-Pech", title="Assistant Professor of Chemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=ngonzalezpec", email="ngonzalezpec@wesleyan.edu"),
            faculty("Hannah Nennig", title="Assistant Professor of the Practice in Chemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=hnennig", email="hnennig@wesleyan.edu"),
            faculty("Alison O'Neil", title="Assistant Professor of Chemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=aoneil", email="aoneil@wesleyan.edu"),
            faculty("Andrea Roberts", title="Professor of the Practice in Chemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=aroberts01", email="aroberts01@wesleyan.edu"),
            faculty("Colin Smith", title="Associate Professor of Chemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=csmith06", email="csmith06@wesleyan.edu"),
            faculty("Erika Taylor", title="Professor of Chemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=eataylor", email="eataylor@wesleyan.edu"),
        ]),
        _dept("COMP", "Department of Computer Science", ["Computer Science"],
               "https://www.wesleyan.edu/mathcs/index.html", [
            faculty("Norman Danner", title="Professor of Computer Science", url="https://www.wesleyan.edu/about/directory/profile.html?id=ndanner", email="ndanner@wesleyan.edu"),
            faculty("Yuxuan Mei", title="Assistant Professor of Computer Science", url="https://www.wesleyan.edu/about/directory/profile.html?id=ymei", email="ymei@wesleyan.edu"),
        ]),
        _dept("EES", "Department of Earth and Environmental Sciences", ["Earth and Environmental Sciences"],
               "https://www.wesleyan.edu/ees/index.html", [
            faculty("Raquel Bryant", title="Assistant Professor of Earth and Environmental Sciences", url="https://www.wesleyan.edu/about/directory/profile.html?id=rbryant", email="rbryant@wesleyan.edu"),
            faculty("Barry Chernoff", title="Professor of Earth and Environmental Sciences", url="https://www.wesleyan.edu/about/directory/profile.html?id=bchernoff", email="bchernoff@wesleyan.edu"),
            faculty("Anthony Cummings", title="Professor of Climate Change", url="https://www.wesleyan.edu/about/directory/profile.html?id=arcummings", email="arcummings@wesleyan.edu"),
            faculty("Martha Gilmore", title="Professor of Earth and Environmental Sciences", url="https://www.wesleyan.edu/about/directory/profile.html?id=mgilmore", email="mgilmore@wesleyan.edu"),
            faculty("James Greenwood", title="Associate Professor of Earth and Environmental Sciences", url="https://www.wesleyan.edu/about/directory/profile.html?id=jgreenwood", email="jgreenwood@wesleyan.edu"),
            faculty("Timothy Ku", title="Associate Professor of Earth and Environmental Sciences", url="https://www.wesleyan.edu/about/directory/profile.html?id=tcku", email="tcku@wesleyan.edu"),
            faculty("Suzanne OConnell", title="Professor of Earth and Environmental Sciences", url="https://www.wesleyan.edu/about/directory/profile.html?id=soconnell", email="soconnell@wesleyan.edu"),
            faculty("Phillip Resor", title="Professor of Earth and Environmental Sciences", url="https://www.wesleyan.edu/about/directory/profile.html?id=presor", email="presor@wesleyan.edu"),
            faculty("Dana Royer", title="Professor of Earth and Environmental Sciences", url="https://www.wesleyan.edu/about/directory/profile.html?id=droyer", email="droyer@wesleyan.edu"),
            faculty("Ellen Thomas", title="Curator of Paleontology of the Joe Webb Peoples Museum", url="https://www.wesleyan.edu/about/directory/profile.html?id=ethomas", email="ethomas@wesleyan.edu"),
            faculty("Sanaz Vajedian", title="Assistant Professor of the Practice in Earth and Environmental Sciences", url="https://www.wesleyan.edu/about/directory/profile.html?id=svajedian", email="svajedian@wesleyan.edu"),
            faculty("Johan Varekamp", title="Curator of Mineralogy and Petrology of the Joe Webb Pe", url="https://www.wesleyan.edu/about/directory/profile.html?id=jvarekamp", email="jvarekamp@wesleyan.edu"),
        ]),
        _dept("MATH", "Department of Mathematics", ["Mathematics"],
               "https://www.wesleyan.edu/mathcs/index.html", [
            faculty("Ilesanmi Adeboye", title="Associate Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=iadeboye", email="iadeboye@wesleyan.edu"),
            faculty("Wai Kiu Chan", title="Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=wkchan", email="wkchan@wesleyan.edu"),
            faculty("Karen L. Collins", title="Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=kcollins", email="kcollins@wesleyan.edu"),
            faculty("David Constantine", title="Associate Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=dconstantine", email="dconstantine@wesleyan.edu"),
            faculty("Cameron Hill", title="Associate Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=cdhill", email="cdhill@wesleyan.edu"),
            faculty("Daniel Krizanc", title="Professor of Computer Science", url="https://www.wesleyan.edu/about/directory/profile.html?id=dkrizanc", email="dkrizanc@wesleyan.edu"),
            faculty("Alex Kruckman", title="Associate Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=akruckman", email="akruckman@wesleyan.edu"),
            faculty("Constance Leidy", title="Associate Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=cleidy", email="cleidy@wesleyan.edu"),
            faculty("Han Li", title="Associate Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=hli03", email="hli03@wesleyan.edu"),
            faculty("Dan Licata", title="Associate Professor of Computer Science", url="https://www.wesleyan.edu/about/directory/profile.html?id=dlicata", email="dlicata@wesleyan.edu"),
            faculty("James Lipton", title="Professor of Computer Science", url="https://www.wesleyan.edu/about/directory/profile.html?id=jlipton", email="jlipton@wesleyan.edu"),
            faculty("Victoria Manfredi", title="Associate Professor of Computer Science", url="https://www.wesleyan.edu/about/directory/profile.html?id=vumanfredi", email="vumanfredi@wesleyan.edu"),
            faculty("David Pollack", title="Associate Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=dpollack", email="dpollack@wesleyan.edu"),
            faculty("Felipe Ramirez", title="Associate Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=framirez", email="framirez@wesleyan.edu"),
            faculty("Christopher Rasmussen", title="Associate Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=crasmussen", email="crasmussen@wesleyan.edu"),
            faculty("Sonia Roberts", title="Assistant Professor of Computer Science", url="https://www.wesleyan.edu/about/directory/profile.html?id=sfroberts", email="sfroberts@wesleyan.edu"),
            faculty("Nikolas Schonsheck", title="Assistant Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=nschonsheck", email="nschonsheck@wesleyan.edu"),
            faculty("Emily Stark", title="Assistant Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=estark", email="estark@wesleyan.edu"),
            faculty("Iris Yoon", title="Assistant Professor of Mathematics", url="https://www.wesleyan.edu/about/directory/profile.html?id=hyoon", email="hyoon@wesleyan.edu"),
            faculty("Sebastian Zimmeck", title="Associate Professor of Computer Science", url="https://www.wesleyan.edu/about/directory/profile.html?id=szimmeck", email="szimmeck@wesleyan.edu"),
        ]),
        _dept("MBB", "Department of Molecular Biology and Biochemistry", ["Molecular Biology and Biochemistry"],
               "https://www.wesleyan.edu/mbb/index.html", [
            faculty("Cori Anderson", title="Professor of the Practice in Molecular Biology and Biochemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=canderson05", email="canderson05@wesleyan.edu"),
            faculty("Oriana Fisher", title="Assistant Professor of Molecular Biology and Biochemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=ofisher", email="ofisher@wesleyan.edu"),
            faculty("Manju Hingorani", title="Professor in Molecular Biology & Biochemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=mhingorani", email="mhingorani@wesleyan.edu"),
            faculty("Scott Holmes", title="Professor of Molecular Biology and Biochemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=sholmes", email="sholmes@wesleyan.edu"),
            faculty("Amy MacQueen", title="Associate Professor of Molecular Biology and Biochemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=amacqueen", email="amacqueen@wesleyan.edu"),
            faculty("Donald Oliver", title="Professor of Molecular Biology and Biochemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=doliver", email="doliver@wesleyan.edu"),
            faculty("Rich Olson", title="Professor of Molecular Biology and Biochemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=rolson", email="rolson@wesleyan.edu"),
            faculty("Teresita Padilla-Benavides", title="Associate Professor of Molecular Biology and Biochemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=tpadillabena", email="tpadillabena@wesleyan.edu"),
            faculty("Alison Wirshing", title="Assistant Professor of Molecular Biology and Biochemistry", url="https://www.wesleyan.edu/about/directory/profile.html?id=awirshing", email="awirshing@wesleyan.edu"),
        ]),
        _dept("NSB", "Neuroscience and Behavior Program", ["Neuroscience and Behavior"],
               "https://www.wesleyan.edu/nsb/index.html", [
            faculty("Charles Sanislow", title="Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=csanislow", email="csanislow@wesleyan.edu"),
            faculty("Helen Treloar", title="Professor of the Practice in Neuroscience and Behavior", url="https://www.wesleyan.edu/about/directory/profile.html?id=htreloar", email="htreloar@wesleyan.edu"),
        ]),
        _dept("PHYS", "Department of Physics", ["Physics"],
               "https://www.wesleyan.edu/physics/index.html", [
            faculty("Reinhold Blumel", title="Professor of Physics", url="https://www.wesleyan.edu/about/directory/profile.html?id=rblumel", email="rblumel@wesleyan.edu"),
            faculty("Tsampikos Kottos", title="Professor of Physics", url="https://www.wesleyan.edu/about/directory/profile.html?id=tkottos", email="tkottos@wesleyan.edu"),
            faculty("Grace McKenzie-Smith", title="Assistant Professor of Physics", url="https://www.wesleyan.edu/about/directory/profile.html?id=gmckenziesmith", email="gmckenziesmith@wesleyan.edu"),
            faculty("George Paily", title="Professor of the Practice in Physics", url="https://www.wesleyan.edu/about/directory/profile.html?id=gpaily", email="gpaily@wesleyan.edu"),
            faculty("Francis Starr", title="Professor of Physics", url="https://www.wesleyan.edu/about/directory/profile.html?id=fstarr", email="fstarr@wesleyan.edu"),
            faculty("Brian Stewart", title="Professor of Physics", url="https://www.wesleyan.edu/about/directory/profile.html?id=bstewart", email="bstewart@wesleyan.edu"),
            faculty("Min-Feng Tu", title="Professor of the Practice in Physics", url="https://www.wesleyan.edu/about/directory/profile.html?id=mtu", email="mtu@wesleyan.edu"),
        ]),
        _dept("CIS", "College of Integrative Sciences", ["Integrative Sciences"],
               "https://www.wesleyan.edu/cis/", [
            faculty("Anthony Davis", title="Professor of the Practice", url="https://www.wesleyan.edu/about/directory/profile.html?id=adavis02", email="adavis02@wesleyan.edu"),
            faculty("Roy Kilgard", title="Professor of the Practice", url="https://www.wesleyan.edu/about/directory/profile.html?id=rkilgard", email="rkilgard@wesleyan.edu"),
            faculty("Meng-ju Sher", title="Associate Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=msher", email="msher@wesleyan.edu"),
            faculty("Kelly Thayer", title="Assistant Professor of Integrative Sciences", url="https://www.wesleyan.edu/about/directory/profile.html?id=kthayer", email="kthayer@wesleyan.edu"),
        ]),
        _dept("COE", "College of the Environment", ["Environmental Studies"],
               "https://www.wesleyan.edu/coe/academics/index.html", [
            faculty("Christine Caruso", title="Assistant Professor of the Practice in the Bailey College of the Environment", url="https://www.wesleyan.edu/about/directory/profile.html?id=ccaruso", email="ccaruso@wesleyan.edu"),
            faculty("Courtney Fullilove", title="Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=cfullilove", email="cfullilove@wesleyan.edu"),
            faculty("Elijah Huge", title="Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=ehuge", email="ehuge@wesleyan.edu"),
            faculty("Antonio Machado Allison", title="University Professor in the College of the Environment", url="https://www.wesleyan.edu/about/directory/profile.html?id=amachado", email="amachado@wesleyan.edu"),
            faculty("Kathleen (Kate) Miller", title="Assistant Professor of the Practice in Environmental Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=kmiller02", email="kmiller02@wesleyan.edu"),
            faculty("María Ospina", title="Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=mospina", email="mospina@wesleyan.edu"),
            faculty("Rosemary Ostfeld", title="Assistant Professor of the Practice in Environmental Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=rostfeld", email="rostfeld@wesleyan.edu"),
            faculty("Earl Phillips", title="Professor in Environmental Sciences", url="https://www.wesleyan.edu/about/directory/profile.html?id=ewphillips", email="ewphillips@wesleyan.edu"),
            faculty("Helen Poulos", title="Distinguished Associate Professor of the Bailey College of the Environment and Earth and Environmental Sciences", url="https://www.wesleyan.edu/about/directory/profile.html?id=hpoulos", email="hpoulos@wesleyan.edu"),
        ]),
        _dept("QAC", "Quantitative Analysis Center", ["Data Science"],
               "https://www.wesleyan.edu/qac/", [
            faculty("Maryam Gooyabadi", title="Associate Professor of the Practice in Quantitative Analysis", url="https://www.wesleyan.edu/about/directory/profile.html?id=mgooyabadi", email="mgooyabadi@wesleyan.edu"),
            faculty("Emmanuel Kaparakis", title="Professor of the Practice in Quantitate Analysis", url="https://www.wesleyan.edu/about/directory/profile.html?id=mkaparakis", email="mkaparakis@wesleyan.edu"),
            faculty("Antonio Laverghetta", title="Assistant Professor of the Practice in Quantitative Analysis", url="https://www.wesleyan.edu/about/directory/profile.html?id=alaverghetta", email="alaverghetta@wesleyan.edu"),
            faculty("Valerie Nazzaro", title="Professor of the Practice in Quantitative Analysis", url="https://www.wesleyan.edu/about/directory/profile.html?id=vnazzaro", email="vnazzaro@wesleyan.edu"),
            faculty("Pavel Oleinikov", title="Associate Professor of the Practice in Quantitative Analysis", url="https://www.wesleyan.edu/about/directory/profile.html?id=poleinikov", email="poleinikov@wesleyan.edu"),
        ]),
        # ---- Social Sciences ---------------------------------------------
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
               "https://www.wesleyan.edu/anthro/index.html", [
            faculty("A. George Bajalia", title="Assistant Professor of Anthropology", url="https://www.wesleyan.edu/about/directory/profile.html?id=abajalia", email="abajalia@wesleyan.edu"),
            faculty("Anu (Aradhana) Sharma", title="Professor of Anthropology", url="https://www.wesleyan.edu/about/directory/profile.html?id=asharma", email="asharma@wesleyan.edu"),
            faculty("Elizabeth Traube", title="Professor of Anthropology", url="https://www.wesleyan.edu/about/directory/profile.html?id=etraube", email="etraube@wesleyan.edu"),
            faculty("Joseph Weiss", title="Associate Professor of Anthropology", url="https://www.wesleyan.edu/about/directory/profile.html?id=jweiss02", email="jweiss02@wesleyan.edu"),
            faculty("Margot Weiss", title="Associate Professor of Anthropology", url="https://www.wesleyan.edu/about/directory/profile.html?id=mdweiss", email="mdweiss@wesleyan.edu"),
        ]),
        _dept("ECON", "Department of Economics", ["Economics"],
               "https://www.wesleyan.edu/econ/index.html", [
            faculty("Karl Boulware", title="Associate Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=kboulware", email="kboulware@wesleyan.edu"),
            faculty("Carycruz Bueno", title="Assistant Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=cbueno", email="cbueno@wesleyan.edu"),
            faculty("Richard Grossman", title="Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=rgrossman", email="rgrossman@wesleyan.edu"),
            faculty("Christiaan Hogendorn", title="Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=chogendorn", email="chogendorn@wesleyan.edu"),
            faculty("Abigail Hornstein", title="Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=ahornstein", email="ahornstein@wesleyan.edu"),
            faculty("Masami Imai", title="Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=mimai", email="mimai@wesleyan.edu"),
            faculty("Ryuichiro Izumi", title="Associate Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=rizumi", email="rizumi@wesleyan.edu"),
            faculty("Anthony Keats", title="Associate Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=akeats", email="akeats@wesleyan.edu"),
            faculty("Melanie Khamis", title="Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=mkhamis", email="mkhamis@wesleyan.edu"),
            faculty("Omer Koru", title="Assistant Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=okoru", email="okoru@wesleyan.edu"),
            faculty("David Kuenzel", title="Associate Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=dkuenzel", email="dkuenzel@wesleyan.edu"),
            faculty("Tyler Porter", title="Assistant Professor of the Practice in Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=tporter01", email="tporter01@wesleyan.edu"),
            faculty("Alexandra Schubert", title="Assistant Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=avschubert", email="avschubert@wesleyan.edu"),
            faculty("Francois Seyler", title="Assistant Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=fseyler", email="fseyler@wesleyan.edu"),
            faculty("Damien Sheehan-Connor", title="Associate Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=dsheehanconn", email="dsheehanconn@wesleyan.edu"),
            faculty("Gilbert Skillman", title="Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=gskillman", email="gskillman@wesleyan.edu"),
            faculty("Balazs Zelity", title="Assistant Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=bzelity", email="bzelity@wesleyan.edu"),
            faculty("Xiaoxue Zhao", title="Assistant Professor of Economics", url="https://www.wesleyan.edu/about/directory/profile.html?id=xzhao02", email="xzhao02@wesleyan.edu"),
        ]),
        _dept("GOVT", "Department of Government", ["Government"],
               "https://www.wesleyan.edu/academics/departments/government/people.html", [
            faculty("Sonali Chakravarti", title="Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=schakravarti", email="schakravarti@wesleyan.edu"),
            faculty("Logan Dancey", title="Associate Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=ldancey", email="ldancey@wesleyan.edu"),
            faculty("Lindsay Dolan", title="Associate Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=ldolan", email="ldolan@wesleyan.edu"),
            faculty("Marc Eisner", title="Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=meisner", email="meisner@wesleyan.edu"),
            faculty("Douglas Foyle", title="Associate Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=dfoyle", email="dfoyle@wesleyan.edu"),
            faculty("Erika Franklin Fowler", title="Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=efowler", email="efowler@wesleyan.edu"),
            faculty("Giulio Gallarotti", title="Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=ggallarotti", email="ggallarotti@wesleyan.edu"),
            faculty("Mary Alice Haddad", title="Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=mahaddad", email="mahaddad@wesleyan.edu"),
            faculty("Nina Hagel", title="Assistant Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=nhagel", email="nhagel@wesleyan.edu"),
            faculty("Kolby Hanson", title="Assistant Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=krhanson", email="krhanson@wesleyan.edu"),
            faculty("Basak Kus", title="Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=bkus", email="bkus@wesleyan.edu"),
            faculty("Alyx Mark", title="Associate Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=amark", email="amark@wesleyan.edu"),
            faculty("Ioana Emy Matesan", title="Associate Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=imatesan", email="imatesan@wesleyan.edu"),
            faculty("James McGuire", title="Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=jmcguire", email="jmcguire@wesleyan.edu"),
            faculty("Steven Moore", title="Assistant Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=stmoore", email="stmoore@wesleyan.edu"),
            faculty("Justin Peck", title="Associate Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=jcpeck", email="jcpeck@wesleyan.edu"),
            faculty("Hari Ramesh", title="Assistant Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=hramesh", email="hramesh@wesleyan.edu"),
            faculty("Peter Rutland", title="Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=prutland", email="prutland@wesleyan.edu"),
        ]),
        _dept("PSYC", "Department of Psychology", ["Psychology"],
               "https://www.wesleyan.edu/academics/departments/psychology/people.html", [
            faculty("Hilary Barth", title="Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=hbarth", email="hbarth@wesleyan.edu"),
            faculty("Sarah Carney", title="Associate Professor of the Practice in Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=scarney", email="scarney@wesleyan.edu"),
            faculty("Lucy De Souza", title="Assistant Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=ldesouza", email="ldesouza@wesleyan.edu"),
            faculty("Lisa Dierker", title="Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=ldierker", email="ldierker@wesleyan.edu"),
            faculty("Royette Dubar", title="Associate Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=rtdubar", email="rtdubar@wesleyan.edu"),
            faculty("Barbara Juhasz", title="Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=bjuhasz", email="bjuhasz@wesleyan.edu"),
            faculty("Kyungmi Kim", title="Associate Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=kkim01", email="kkim01@wesleyan.edu"),
            faculty("Matthew Kurtz", title="Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=mkurtz", email="mkurtz@wesleyan.edu"),
            faculty("Alexis May", title="Associate Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=amay01", email="amay01@wesleyan.edu"),
            faculty("Jill Morawski", title="Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=jmorawski", email="jmorawski@wesleyan.edu"),
            faculty("Andrea Negrete", title="Assistant Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=anegrete", email="anegrete@wesleyan.edu"),
            faculty("Samantha O'Connell", title="Assistant Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=sroconnell", email="sroconnell@wesleyan.edu"),
            faculty("Andrea Patalano", title="Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=apatalano", email="apatalano@wesleyan.edu"),
            faculty("Michael Perez", title="Assistant Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=mperez01", email="mperez01@wesleyan.edu"),
            faculty("Scott Plous", title="Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=splous", email="splous@wesleyan.edu"),
            faculty("Patricia Rodriguez Mosquera", title="Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=prodriguezmo", email="prodriguezmo@wesleyan.edu"),
            faculty("Steven Stemler", title="Professor of Psychology", url="https://www.wesleyan.edu/about/directory/profile.html?id=sstemler", email="sstemler@wesleyan.edu"),
        ]),
        _dept("SOC", "Department of Sociology", ["Sociology"],
               "https://www.wesleyan.edu/soc/index.html", [
            faculty("Robyn Autry", title="Associate Professor of Sociology", url="https://www.wesleyan.edu/about/directory/profile.html?id=rautry", email="rautry@wesleyan.edu"),
            faculty("Abigail Boggs", title="Assistant Professor of Sociology", url="https://www.wesleyan.edu/about/directory/profile.html?id=aboggs", email="aboggs@wesleyan.edu"),
            faculty("Jonathan Cutler", title="Associate Professor of Sociology", url="https://www.wesleyan.edu/about/directory/profile.html?id=jcutler", email="jcutler@wesleyan.edu"),
            faculty("Greg Goldberg", title="Associate Professor of Sociology", url="https://www.wesleyan.edu/about/directory/profile.html?id=ggoldberg", email="ggoldberg@wesleyan.edu"),
            faculty("Benjamin Haber", title="Assistant Professor of Sociology", url="https://www.wesleyan.edu/about/directory/profile.html?id=bhaber", email="bhaber@wesleyan.edu"),
            faculty("Kristen Miller", title="Assistant Professor of Sociology", url="https://www.wesleyan.edu/about/directory/profile.html?id=klmiller", email="klmiller@wesleyan.edu"),
            faculty("Courtney Patterson-Faye", title="Associate Professor of Sociology", url="https://www.wesleyan.edu/about/directory/profile.html?id=cpatterson", email="cpatterson@wesleyan.edu"),
        ]),
        _dept("CSS", "College of Social Studies", ["Social Studies"],
               "https://www.wesleyan.edu/css/", [
            faculty("Erik Grimmer-Solem", title="Professor in the College of Social Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=egrimmer", email="egrimmer@wesleyan.edu"),
            faculty("J. Donald Moon", title="Professor in the College of Social St", url="https://www.wesleyan.edu/about/directory/profile.html?id=dmoon", email="dmoon@wesleyan.edu"),
            faculty("Daniel Steinmetz-Jenkins", title="Assistant Professor in the College of Social Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=dsteinmetzje", email="dsteinmetzje@wesleyan.edu"),
            faculty("Sarah Wiliarty", title="Associate Professor of Government", url="https://www.wesleyan.edu/about/directory/profile.html?id=swiliarty", email="swiliarty@wesleyan.edu"),
        ]),
        _dept("CSPL", "Allbritton Center for the Study of Public Life", ["Public Policy"],
               "https://www.wesleyan.edu/allbritton/", [
            faculty("Khalilah Brown-Dean", title="Distinguished Professor of Civic Engagement", url="https://www.wesleyan.edu/about/directory/profile.html?id=kbrowndean", email="kbrowndean@wesleyan.edu"),
            faculty("Robert Cassidy", title="Assistant Professor of the Practice in the Allbritton Center for the Study of Public Life", url="https://www.wesleyan.edu/about/directory/profile.html?id=rcassidy", email="rcassidy@wesleyan.edu"),
            faculty("Stephan Sonnenberg", title="Associate Professor of the Practice in Human Rights Advocacy and Conflict Resolution", url="https://www.wesleyan.edu/about/directory/profile.html?id=ssonnenberg", email="ssonnenberg@wesleyan.edu"),
        ]),
        # ---- Humanities --------------------------------------------------
        _dept("ENGL", "Department of English", ["English"],
               "https://www.wesleyan.edu/english/index.html", [
            faculty("Sally Bachner", title="Associate Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=sbachner", email="sbachner@wesleyan.edu"),
            faculty("Marina Bilbija", title="Assistant Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=mbilbija", email="mbilbija@wesleyan.edu"),
            faculty("Sierra Eckert", title="Assistant Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=seckert", email="seckert@wesleyan.edu"),
            faculty("Ren Ellis Neyra", title="Associate Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=rellisneyra", email="rellisneyra@wesleyan.edu"),
            faculty("Shangyang Fang", title="Assistant Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=sfang01", email="sfang01@wesleyan.edu"),
            faculty("Harris Friedberg", title="Associate Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=hfriedberg", email="hfriedberg@wesleyan.edu"),
            faculty("Matthew Garrett", title="Associate Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=mcgarrett", email="mcgarrett@wesleyan.edu"),
            faculty("Rachel Heng", title="Assistant Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=qheng", email="qheng@wesleyan.edu"),
            faculty("Douglas Martin", title="Associate Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=damartin", email="damartin@wesleyan.edu"),
            faculty("Sean McCann", title="Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=smccann", email="smccann@wesleyan.edu"),
            faculty("Rashida McMahon", title="Associate Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=rshawmcmahon", email="rshawmcmahon@wesleyan.edu"),
            faculty("Maaza Mengiste", title="Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=mmengiste", email="mmengiste@wesleyan.edu"),
            faculty("Ruth Nisse", title="Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=rnisse", email="rnisse@wesleyan.edu"),
            faculty("Tyrone Palmer", title="Assistant Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=tspalmer", email="tspalmer@wesleyan.edu"),
            faculty("Joel Pfister", title="Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=jpfister", email="jpfister@wesleyan.edu"),
            faculty("Ashraf Rushdy", title="Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=arushdy", email="arushdy@wesleyan.edu"),
            faculty("Lily Saint", title="Associate Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=lsaint", email="lsaint@wesleyan.edu"),
            faculty("Hirsh Sawhney", title="Associate Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=hsawhney", email="hsawhney@wesleyan.edu"),
            faculty("Courtney Weiss Smith", title="Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=csmith03", email="csmith03@wesleyan.edu"),
            faculty("Amy Tang", title="Associate Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=atang", email="atang@wesleyan.edu"),
            faculty("Danielle Vogel", title="Associate Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=dvogel", email="dvogel@wesleyan.edu"),
            faculty("Stephanie Weiner", title="Professor of English", url="https://www.wesleyan.edu/about/directory/profile.html?id=sweiner", email="sweiner@wesleyan.edu"),
        ]),
        _dept("HIST", "Department of History", ["History"],
               "https://www.wesleyan.edu/history/index.html", [
            faculty("Nathanael Greene", title="Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=ngreene", email="ngreene@wesleyan.edu"),
            faculty("Ethan Kleinberg", title="Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=ekleinberg", email="ekleinberg@wesleyan.edu"),
            faculty("Jeffers Lennox", title="Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=jlennox", email="jlennox@wesleyan.edu"),
            faculty("Valeria Lopez Fadul", title="Associate Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=vlopezfadul", email="vlopezfadul@wesleyan.edu"),
            faculty("Cecilia Miller", title="Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=cmiller", email="cmiller@wesleyan.edu"),
            faculty("Kristin Oberiano", title="Assistant Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=koberiano", email="koberiano@wesleyan.edu"),
            faculty("Maryam Patton", title="Assistant Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=mpatton", email="mpatton@wesleyan.edu"),
            faculty("William Pinch", title="Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=wpinch", email="wpinch@wesleyan.edu"),
            faculty("Gary Shaw", title="Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=gshaw", email="gshaw@wesleyan.edu"),
            faculty("Joseph Slaughter", title="Associate Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=jslaughter01", email="jslaughter01@wesleyan.edu"),
            faculty("Ying Jia Tan", title="Associate Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=ytan", email="ytan@wesleyan.edu"),
            faculty("Jennifer Tucker", title="Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=jtucker", email="jtucker@wesleyan.edu"),
            faculty("Laura Ann Twagira", title="Associate Professor of History", url="https://www.wesleyan.edu/about/directory/profile.html?id=ltwagira", email="ltwagira@wesleyan.edu"),
        ]),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"],
               "https://www.wesleyan.edu/philosophy/index.html", [
            faculty("Stephen Angle", title="Professor of Philosophy", url="https://www.wesleyan.edu/about/directory/profile.html?id=sangle", email="sangle@wesleyan.edu"),
            faculty("Steven Horst", title="Professor of Philosophy", url="https://www.wesleyan.edu/about/directory/profile.html?id=shorst", email="shorst@wesleyan.edu"),
            faculty("Tushar Irani", title="Professor of Philosophy", url="https://www.wesleyan.edu/about/directory/profile.html?id=tirani", email="tirani@wesleyan.edu"),
            faculty("Joseph Rouse", title="Professor of Philosophy", url="https://www.wesleyan.edu/about/directory/profile.html?id=jrouse", email="jrouse@wesleyan.edu"),
            faculty("Sanford Shieh", title="Professor of Philosophy", url="https://www.wesleyan.edu/about/directory/profile.html?id=sshieh", email="sshieh@wesleyan.edu"),
            faculty("Elise Springer", title="Associate Professor of Philosophy", url="https://www.wesleyan.edu/about/directory/profile.html?id=espringer", email="espringer@wesleyan.edu"),
            faculty("Nicholas Whittaker", title="Assistant Professor of Philosophy", url="https://www.wesleyan.edu/about/directory/profile.html?id=nwhittaker", email="nwhittaker@wesleyan.edu"),
        ]),
        _dept("RELI", "Department of Religion", ["Religion"],
               "https://www.wesleyan.edu/religion/index.html", [
            faculty("Ron Cameron", title="Professor of Religion", url="https://www.wesleyan.edu/about/directory/profile.html?id=rcameron", email="rcameron@wesleyan.edu"),
            faculty("Elizabeth A. McAlister", title="Professor of Religion", url="https://www.wesleyan.edu/about/directory/profile.html?id=emcalister", email="emcalister@wesleyan.edu"),
            faculty("Andrew Quintman", title="Associate Professor of Religion", url="https://www.wesleyan.edu/about/directory/profile.html?id=aquintman", email="aquintman@wesleyan.edu"),
            faculty("Mary-Jane Rubenstein", title="Professor of Religion", url="https://www.wesleyan.edu/about/directory/profile.html?id=mrubenstein", email="mrubenstein@wesleyan.edu"),
            faculty("Tanner Walker", title="Assistant Professor of Religion", url="https://www.wesleyan.edu/about/directory/profile.html?id=tewalker", email="tewalker@wesleyan.edu"),
        ]),
        _dept("CLST", "Department of Classical Studies", ["Classical Studies"],
               "https://www.wesleyan.edu/academics/departments/classical-studies/people.html", [
            faculty("Kate Birney", title="Associate Professor of Classical Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=kbirney", email="kbirney@wesleyan.edu"),
            faculty("José Antonio Cancino Alfaro", title="Assistant Professor of Classical Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=jcancinoalfa", email="jcancinoalfa@wesleyan.edu"),
            faculty("Eirene Visvardi", title="Associate Professor of Classical Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=evisvardi", email="evisvardi@wesleyan.edu"),
        ]),
        _dept("COL", "College of Letters", ["Literature", "History", "Philosophy"],
               "https://www.wesleyan.edu/col/", [
            faculty("Charles Barber", title="Professor of the Practice in Letters", url="https://www.wesleyan.edu/about/directory/profile.html?id=cmbarber", email="cmbarber@wesleyan.edu"),
            faculty("Hadel Jarada", title="Assistant Professor of Letters", url="https://www.wesleyan.edu/about/directory/profile.html?id=hjarada", email="hjarada@wesleyan.edu"),
            faculty("Typhaine Leservot", title="Associate Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=tleservot", email="tleservot@wesleyan.edu"),
            faculty("Gabrielle Ponce-Hegenauer", title="Associate Professor of Letters", url="https://www.wesleyan.edu/about/directory/profile.html?id=gponce", email="gponce@wesleyan.edu"),
            faculty("Daniel Smyth", title="Associate Professor of Letters", url="https://www.wesleyan.edu/about/directory/profile.html?id=dsmyth", email="dsmyth@wesleyan.edu"),
            faculty("Jesse Torgerson", title="Associate Professor of Letters", url="https://www.wesleyan.edu/about/directory/profile.html?id=jtorgerson", email="jtorgerson@wesleyan.edu"),
            faculty("Kari Weil", title="University Professor of Letters", url="https://www.wesleyan.edu/about/directory/profile.html?id=kweil", email="kweil@wesleyan.edu"),
        ]),
        _dept("ROML", "Department of Romance Languages and Literatures", ["French", "Italian", "Spanish"],
               "https://www.wesleyan.edu/romance/", [
            faculty("Nadja Aksamija", title="Associate Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=naksamija", email="naksamija@wesleyan.edu"),
            faculty("Michael Armstrong-Roche", title="Associate Professor of Spanish", url="https://www.wesleyan.edu/about/directory/profile.html?id=marmstrong", email="marmstrong@wesleyan.edu"),
            faculty("Robert Conn", title="Professor of Spanish", url="https://www.wesleyan.edu/about/directory/profile.html?id=rconn", email="rconn@wesleyan.edu"),
            faculty("Andrew Curran", title="Professor of French", url="https://www.wesleyan.edu/about/directory/profile.html?id=acurran", email="acurran@wesleyan.edu"),
            faculty("Carolina Diaz", title="Assistant Professor of Spanish", url="https://www.wesleyan.edu/about/directory/profile.html?id=cdiaz", email="cdiaz@wesleyan.edu"),
            faculty("Michael Meere", title="Associate Professor of French", url="https://www.wesleyan.edu/about/directory/profile.html?id=mmeere", email="mmeere@wesleyan.edu"),
            faculty("Ellen Nerenberg", title="Professor of Italian", url="https://www.wesleyan.edu/about/directory/profile.html?id=enerenberg", email="enerenberg@wesleyan.edu"),
            faculty("Liana Pshevorska", title="Associate Professor of the Practice in French", url="https://www.wesleyan.edu/about/directory/profile.html?id=lpshevorska", email="lpshevorska@wesleyan.edu"),
            faculty("Jeff Rider", title="Professor of French", url="https://www.wesleyan.edu/about/directory/profile.html?id=jrider", email="jrider@wesleyan.edu"),
            faculty("Olga Sendra Ferrer", title="Associate Professor of Spanish", url="https://www.wesleyan.edu/about/directory/profile.html?id=osendra", email="osendra@wesleyan.edu"),
            faculty("Xinyi Wei", title="Assistant Professor of French", url="https://www.wesleyan.edu/about/directory/profile.html?id=xwei", email="xwei@wesleyan.edu"),
            faculty("Camilla Zamboni", title="Associate Professor of the Practice in Italian", url="https://www.wesleyan.edu/about/directory/profile.html?id=czamboni", email="czamboni@wesleyan.edu"),
        ]),
        _dept("GRST", "German Studies", ["German Studies"],
               "https://www.wesleyan.edu/german/index.html", [
            faculty("Martin Baeumel", title="Associate Professor of German Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=mbaeumel", email="mbaeumel@wesleyan.edu"),
            faculty("Ljudmila Bilkic", title="Assistant Professor of the Practice in German Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=lbilkic", email="lbilkic@wesleyan.edu"),
            faculty("Ulrich Plass", title="Professor of German Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=uplass", email="uplass@wesleyan.edu"),
        ]),
        _dept("REES", "Russian, East European, and Eurasian Studies", ["Russian and Eastern European Studies"],
               "https://www.wesleyan.edu/russian/index.html", [
            faculty("Joseph Fitzpatrick", title="Professor of the Practice", url="https://www.wesleyan.edu/about/directory/profile.html?id=jjfitzpatric", email="jjfitzpatric@wesleyan.edu"),
            faculty("Susanne Fusso", title="Professor of Russian", url="https://www.wesleyan.edu/about/directory/profile.html?id=sfusso", email="sfusso@wesleyan.edu"),
            faculty("Natasha Karageorgos", title="Associate Professor of the Practice in Russian", url="https://www.wesleyan.edu/about/directory/profile.html?id=nkarageorgos", email="nkarageorgos@wesleyan.edu"),
            faculty("Justine Quijada", title="Associate Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=jquijada", email="jquijada@wesleyan.edu"),
            faculty("Victoria Smolkin", title="Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=vsmolkin", email="vsmolkin@wesleyan.edu"),
            faculty("Roman Utkin", title="Associate Professor of Russian", url="https://www.wesleyan.edu/about/directory/profile.html?id=rutkin", email="rutkin@wesleyan.edu"),
        ]),
        _dept("CEAS", "College of East Asian Studies", ["East Asian Studies"],
               "https://www.wesleyan.edu/ceas/", [
            faculty("Scott Aalgaard", title="Associate Professor of East Asian Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=saalgaard", email="saalgaard@wesleyan.edu"),
            faculty("Hyejoo Back", title="Professor of the Practice in East Asian Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=hback", email="hback@wesleyan.edu"),
            faculty("Joan Cho", title="Associate Professor of East Asian Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=jecho", email="jecho@wesleyan.edu"),
            faculty("Lisa Dombrowski", title="Professor of East Asian Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=ldombrowski", email="ldombrowski@wesleyan.edu"),
            faculty("Wei Gong", title="Associate Professor of the Practice in East Asian Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=wgong", email="wgong@wesleyan.edu"),
            faculty("Miyuki Hatano-Cohen", title="Assistant Professor of the Practice in East Asian Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=mhatanocohen", email="mhatanocohen@wesleyan.edu"),
            faculty("Yu-ting Huang", title="Assistant Professor of East Asian Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=yhuang05", email="yhuang05@wesleyan.edu"),
            faculty("Mengjun Liu", title="Associate Professor of the Practice in East Asian Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=mliu", email="mliu@wesleyan.edu"),
            faculty("Naho Maruta", title="Professor of the Practice in East Asian Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=nmaruta", email="nmaruta@wesleyan.edu"),
            faculty("Jahyon Park", title="Assistant Professor of East Asian Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=jpark07", email="jpark07@wesleyan.edu"),
            faculty("Takeshi Watanabe", title="Associate Professor of East Asian Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=twatanabe", email="twatanabe@wesleyan.edu"),
        ]),
        _dept("CJST", "Center for Jewish Studies", ["Jewish and Israel Studies"],
               "https://www.wesleyan.edu/cjs/", [
            faculty("Dalit Katz", title="University Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=dkatz01", email="dkatz01@wesleyan.edu"),
            faculty("Avner Shavit", title="Assistant Professor of the Practice in Jewish Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=ashavit", email="ashavit@wesleyan.edu"),
        ]),
        _dept("WRIT", "Shapiro Center for Writing", ["Writing"],
               "https://www.wesleyan.edu/shapirocenter/", [
            faculty("Merve Emre", title="University Professor of Creative Writing and Criticism", url="https://www.wesleyan.edu/about/directory/profile.html?id=memre", email="memre@wesleyan.edu"),
            faculty("Elizabeth (Beth) Hepford", title="Associate Professor of the Practice in TESOL", url="https://www.wesleyan.edu/about/directory/profile.html?id=ehepford", email="ehepford@wesleyan.edu"),
            faculty("Lauren Silber", title="Professor of the Practice in Academic Writing", url="https://www.wesleyan.edu/about/directory/profile.html?id=lsilber", email="lsilber@wesleyan.edu"),
        ]),
        # ---- Arts --------------------------------------------------------
        _dept("ARHA", "Department of Art and Art History", ["Art History", "Studio Art"],
               "https://www.wesleyan.edu/art/", [
            faculty("Joseph Ackley", title="Associate Professor of Art History", url="https://www.wesleyan.edu/about/directory/profile.html?id=jackley", email="jackley@wesleyan.edu"),
            faculty("Talia Andrei", title="Associate Professor of Art History", url="https://www.wesleyan.edu/about/directory/profile.html?id=tandrei", email="tandrei@wesleyan.edu"),
            faculty("Claire Grace", title="Associate Professor of Art History", url="https://www.wesleyan.edu/about/directory/profile.html?id=cgrace", email="cgrace@wesleyan.edu"),
            faculty("Ilana Harris-Babou", title="Assistant Professor of Art", url="https://www.wesleyan.edu/about/directory/profile.html?id=iharrisbabou", email="iharrisbabou@wesleyan.edu"),
            faculty("Yu Nong Khew", title="Assistant Professor of Art", url="https://www.wesleyan.edu/about/directory/profile.html?id=ykhew", email="ykhew@wesleyan.edu"),
            faculty("Katherine Kuenzli", title="Professor of Art History", url="https://www.wesleyan.edu/about/directory/profile.html?id=kkuenzli", email="kkuenzli@wesleyan.edu"),
            faculty("Christian Nakarado", title="Assistant Professor of Art", url="https://www.wesleyan.edu/about/directory/profile.html?id=cnakarado", email="cnakarado@wesleyan.edu"),
            faculty("Tammy Nguyen", title="Associate Professor of Art", url="https://www.wesleyan.edu/about/directory/profile.html?id=tvnguyen", email="tvnguyen@wesleyan.edu"),
            faculty("Okechukwu Nwafor", title="Associate Professor of Art History", url="https://www.wesleyan.edu/about/directory/profile.html?id=onwafor", email="onwafor@wesleyan.edu"),
            faculty("Julia Randall", title="Associate Professor of Art", url="https://www.wesleyan.edu/about/directory/profile.html?id=jrandall", email="jrandall@wesleyan.edu"),
            faculty("Sasha Rudensky", title="Associate Professor of Art", url="https://www.wesleyan.edu/about/directory/profile.html?id=arudensky", email="arudensky@wesleyan.edu"),
            faculty("Joseph Siry", title="Professor of Art History", url="https://www.wesleyan.edu/about/directory/profile.html?id=jsiry", email="jsiry@wesleyan.edu"),
            faculty("Tula Telfair", title="Professor of Art", url="https://www.wesleyan.edu/about/directory/profile.html?id=ttelfair", email="ttelfair@wesleyan.edu"),
            faculty("Erica Wessmann", title="Assistant Professor of Art", url="https://www.wesleyan.edu/about/directory/profile.html?id=ewessmann", email="ewessmann@wesleyan.edu"),
        ]),
        _dept("MUSC", "Department of Music", ["Music"],
               "https://www.wesleyan.edu/music/index.html", [
            faculty("Jane Alden", title="Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=jalden01", email="jalden01@wesleyan.edu"),
            faculty("Neely Bruce", title="Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=nbruce", email="nbruce@wesleyan.edu"),
            faculty("Eric Charry", title="Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=echarry", email="echarry@wesleyan.edu"),
            faculty("Alcee Chriss", title="Assistant Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=achriss", email="achriss@wesleyan.edu"),
            faculty("John Dankwa", title="Assistant Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=jdankwa", email="jdankwa@wesleyan.edu"),
            faculty("Saida Daukeyeva", title="Assistant Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=sdaukeyeva", email="sdaukeyeva@wesleyan.edu"),
            faculty("Roger Mathew Grant", title="Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=rgrant01", email="rgrant01@wesleyan.edu"),
            faculty("I. Harjito", title="University Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=iharjito", email="iharjito@wesleyan.edu"),
            faculty("Jay Hoggard", title="Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=jhoggard", email="jhoggard@wesleyan.edu"),
            faculty("Darius Jones", title="Assistant Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=djones06", email="djones06@wesleyan.edu"),
            faculty("Jin Hi Kim", title="Assistant Professor of the Practice in Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=jkim14", email="jkim14@wesleyan.edu"),
            faculty("Ronald Kuivila", title="Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=rkuivila", email="rkuivila@wesleyan.edu"),
            faculty("Paula Matthusen", title="Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=pmatthusen", email="pmatthusen@wesleyan.edu"),
            faculty("James Praznik", title="Assistant Professor of the Practice in Music and Technical Director", url="https://www.wesleyan.edu/about/directory/profile.html?id=jpraznik", email="jpraznik@wesleyan.edu"),
            faculty("Régulo Stabilito", title="Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=rstabilito", email="rstabilito@wesleyan.edu"),
            faculty("Prof. Sumarsam", title="Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=sumarsam", email="sumarsam@wesleyan.edu"),
            faculty("Su Zheng", title="Associate Professor of Music", url="https://www.wesleyan.edu/about/directory/profile.html?id=szheng", email="szheng@wesleyan.edu"),
        ]),
        _dept("THEA", "Department of Theater", ["Theater"],
               "https://www.wesleyan.edu/academics/departments/theater/people.html", [
            faculty("Rosalie Bochansky", title="Assistant Professor of the Practice in Theater", url="https://www.wesleyan.edu/about/directory/profile.html?id=rbochansky", email="rbochansky@wesleyan.edu"),
            faculty("Katie Brewer Ball", title="Associate Professor of Theater", url="https://www.wesleyan.edu/about/directory/profile.html?id=kbrewerball", email="kbrewerball@wesleyan.edu"),
            faculty("Courtney Gaston", title="Assistant Professor of Theater", url="https://www.wesleyan.edu/about/directory/profile.html?id=cgaston", email="cgaston@wesleyan.edu"),
            faculty("April Hickman", title="Assistant Professor of Theater", url="https://www.wesleyan.edu/about/directory/profile.html?id=amhickman", email="amhickman@wesleyan.edu"),
            faculty("Ronald Jenkins", title="Professor of Theater", url="https://www.wesleyan.edu/about/directory/profile.html?id=rjenkins", email="rjenkins@wesleyan.edu"),
            faculty("Maria-Christina Oliveras", title="Associate Professor of Theater", url="https://www.wesleyan.edu/about/directory/profile.html?id=moliveras", email="moliveras@wesleyan.edu"),
            faculty("Katie Pearl", title="Associate Professor of Theater", url="https://www.wesleyan.edu/about/directory/profile.html?id=kpearl", email="kpearl@wesleyan.edu"),
            faculty("Edwin Sanchez", title="Associate Professor of Theater", url="https://www.wesleyan.edu/about/directory/profile.html?id=esanchez", email="esanchez@wesleyan.edu"),
            faculty("Caleb Spivey", title="Assistant Professor of the Practice in Theater", url="https://www.wesleyan.edu/about/directory/profile.html?id=bspivey", email="bspivey@wesleyan.edu"),
            faculty("Lauren Yeoman", title="Assistant Professor of Theater", url="https://www.wesleyan.edu/about/directory/profile.html?id=lyeoman", email="lyeoman@wesleyan.edu"),
        ]),
        _dept("DANC", "Department of Dance", ["Dance"],
               "https://www.wesleyan.edu/dance/index.html", [
            faculty("Patricia Beaman", title="University Professor of Dance", url="https://www.wesleyan.edu/about/directory/profile.html?id=pbeaman", email="pbeaman@wesleyan.edu"),
            faculty("Douglas Elkins", title="Associate Professor of the Practice in Dance", url="https://www.wesleyan.edu/about/directory/profile.html?id=delkins", email="delkins@wesleyan.edu"),
            faculty("Chelsie McPhilimy", title="Associate Professor of the Practice in Dance", url="https://www.wesleyan.edu/about/directory/profile.html?id=cmcphilimy", email="cmcphilimy@wesleyan.edu"),
            faculty("Joya Powell", title="Associate Professor of Dance", url="https://www.wesleyan.edu/about/directory/profile.html?id=jpowell01", email="jpowell01@wesleyan.edu"),
            faculty("Iddrisu Saaka", title="Associate Professor of Dance", url="https://www.wesleyan.edu/about/directory/profile.html?id=isaaka", email="isaaka@wesleyan.edu"),
        ]),
        _dept("CFILM", "College of Film and the Moving Image", ["Film Studies"],
               "https://www.wesleyan.edu/cfilm/", [
            faculty("Kevin Ball", title="Assistant Professor of Film Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=kdball", email="kdball@wesleyan.edu"),
            faculty("Stephen Collins", title="Professor of Film Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=scollins", email="scollins@wesleyan.edu"),
            faculty("Scott Higgins", title="Professor of Film Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=shiggins", email="shiggins@wesleyan.edu"),
            faculty("Anuja Jain", title="Assistant Professor of Film Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=ajain01", email="ajain01@wesleyan.edu"),
            faculty("Marc Longenecker", title="Professor of the Practice in Film Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=mlongenecker", email="mlongenecker@wesleyan.edu"),
            faculty("Randall MacLowry", title="University Professor of Film Studies and Co-Director of WesDocs", url="https://www.wesleyan.edu/about/directory/profile.html?id=rmaclowry86", email="rmaclowry86@wesleyan.edu"),
            faculty("Richard Parkin", title="Assistant Professor of Film Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=rparkin", email="rparkin@wesleyan.edu"),
            faculty("Mirko Rucnov", title="Associate Professor of the Practice in Film Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=mrucnov", email="mrucnov@wesleyan.edu"),
            faculty("Alejandro Salinas-Albrecht", title="Assistant Professor of the Practice in Film Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=asalinasalbr", email="asalinasalbr@wesleyan.edu"),
            faculty("Sadia Shepard", title="Assistant Professor of Film Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=sshepard", email="sshepard@wesleyan.edu"),
            faculty("Yaya Simakov", title="Assistant Professor of Film Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=ysimakov", email="ysimakov@wesleyan.edu"),
            faculty("Michael Slowik", title="Professor of Film Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=mslowik", email="mslowik@wesleyan.edu"),
            faculty("Tracy Strain", title="Professor of Film Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=tstrain", email="tstrain@wesleyan.edu"),
        ]),
        # ---- Interdisciplinary & Area Studies ----------------------------
        _dept("AFAM", "African American Studies", ["African American Studies"],
               "https://www.wesleyan.edu/afam/index.html", [
            faculty("Garry Bertholf", title="Assistant Professor of African American Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=gbertholf", email="gbertholf@wesleyan.edu"),
            faculty("Kaisha Esty", title="Assistant Professor of African American Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=kesty", email="kesty@wesleyan.edu"),
            faculty("Khalil Johnson", title="Associate Professor of African American Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=kajohnson01", email="kajohnson01@wesleyan.edu"),
            faculty("Jesse Nasta", title="Associate Professor of the Practice in African American Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=jnasta", email="jnasta@wesleyan.edu"),
            faculty("Zaira Simone-Thompson", title="Assistant Professor of African American Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=zsimone", email="zsimone@wesleyan.edu"),
        ]),
        _dept("AMST", "American Studies", ["American Studies"],
               "https://www.wesleyan.edu/amst/index.html", [
            faculty("Megan Glick", title="Associate Professor of American Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=mglick", email="mglick@wesleyan.edu"),
            faculty("Laura Grappo", title="Associate Professor of American Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=lgrappo", email="lgrappo@wesleyan.edu"),
            faculty("Goya Olson", title="Assistant Professor of American Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=golson01", email="golson01@wesleyan.edu"),
            faculty("Roberto Saba", title="Associate Professor of American Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=rsaba", email="rsaba@wesleyan.edu"),
            faculty("Antonina Woodsum", title="Assistant Professor of American Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=awoodsum", email="awoodsum@wesleyan.edu"),
        ]),
        _dept("FGSS", "Feminist, Gender, and Sexuality Studies", ["Feminist, Gender, and Sexuality Studies"],
               "https://www.wesleyan.edu/academics/departments/feminist-gender-sexuality-studies/index.html", [
            faculty("Kerwin Kaye", title="Associate Professor of Feminist", url="https://www.wesleyan.edu/about/directory/profile.html?id=kkaye", email="kkaye@wesleyan.edu"),
            faculty("Naveen Minai", title="Assistant Professor of Feminist", url="https://www.wesleyan.edu/about/directory/profile.html?id=nminai", email="nminai@wesleyan.edu"),
            faculty("Victoria Pitts-Taylor", title="Professor of Feminist", url="https://www.wesleyan.edu/about/directory/profile.html?id=vpitts", email="vpitts@wesleyan.edu"),
        ]),
        _dept("GSAS", "Global South Asian Studies", ["South Asian Studies"],
               "https://www.wesleyan.edu/southasianstudies/index.html", [
            faculty("Hafiz FazaleHaq", title="Assistant Professor of the Practice in South Asian Language and Culture", url="https://www.wesleyan.edu/about/directory/profile.html?id=hfazalehaq", email="hfazalehaq@wesleyan.edu"),
            faculty("Indira Karamcheti", title="Associate Professor of Global South Asian Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=ikaramcheti", email="ikaramcheti@wesleyan.edu"),
            faculty("Hari Krishnan", title="Professor of Dance", url="https://www.wesleyan.edu/about/directory/profile.html?id=hkrishnan", email="hkrishnan@wesleyan.edu"),
        ]),
        _dept("LAST", "Latin American Studies", ["Latin American Studies"],
               "https://www.wesleyan.edu/last/index.html", [
            faculty("Veronica Brownstone", title="Assistant Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=vbrownstone", email="vbrownstone@wesleyan.edu"),
        ]),
        _dept("ARCP", "Archaeology Program", ["Archaeology"],
               "https://www.wesleyan.edu/archprog/index.html", [
            faculty("Katherine Brunson", title="Associate Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=kbrunson", email="kbrunson@wesleyan.edu"),
            faculty("David Reid", title="Assistant Professor of Archaeology", url="https://www.wesleyan.edu/about/directory/profile.html?id=dreid01", email="dreid01@wesleyan.edu"),
        ]),
        _dept("STS", "College of Science and Technology Studies", ["Science in Society"],
               "https://www.wesleyan.edu/sts/", [
            faculty("Elan Abrell", title="Assistant Professor of Science and Technology Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=eabrell", email="eabrell@wesleyan.edu"),
            faculty("Paul Erickson", title="Associate Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=perickson", email="perickson@wesleyan.edu"),
            faculty("Elaine Gan", title="Assistant Professor of Science and Technology Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=egan", email="egan@wesleyan.edu"),
            faculty("Peter Gottschalk", title="Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=pgottschalk", email="pgottschalk@wesleyan.edu"),
            faculty("Anthony Hatch", title="Professor of Science and Technology Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=ahatch", email="ahatch@wesleyan.edu"),
            faculty("Mitali Thakor", title="Associate Professor of Science and Technology Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=mthakor", email="mthakor@wesleyan.edu"),
            faculty("Emily Vasquez", title="Assistant Professor of Science and Technology Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=evasquez", email="evasquez@wesleyan.edu"),
        ]),
        _dept("CODES", "College of Design and Engineering Studies", ["Design and Engineering"],
               "https://www.wesleyan.edu/academics/departments/college-design-engineering-studies/index.html", [
            faculty("Elizabeth Chang-Davidson", title="Assistant Professor of Design and Engineering", url="https://www.wesleyan.edu/about/directory/profile.html?id=echangdavids", email="echangdavids@wesleyan.edu"),
            faculty("Ved Gund", title="Assistant Professor of Design and Engineering", url="https://www.wesleyan.edu/about/directory/profile.html?id=vgund", email="vgund@wesleyan.edu"),
            faculty("Daniel Moller", title="Professor of the Practice in Design and Engineering", url="https://www.wesleyan.edu/about/directory/profile.html?id=dmoller", email="dmoller@wesleyan.edu"),
            faculty("Marcela Oteiza", title="Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=moteiza", email="moteiza@wesleyan.edu"),
            faculty("Greg Voth", title="Professor of Physics", url="https://www.wesleyan.edu/about/directory/profile.html?id=gvoth", email="gvoth@wesleyan.edu"),
            faculty("Christopher Weaver", title="Distinguished Professor of Computational Media", url="https://www.wesleyan.edu/about/directory/profile.html?id=cweaver", email="cweaver@wesleyan.edu"),
        ]),
        _dept("EDST", "Education Studies", ["Education Studies"],
               "https://www.wesleyan.edu/education/index.html", [
            faculty("Rachel Besharat Mann", title="Assistant Professor of Education Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=remann", email="remann@wesleyan.edu"),
            faculty("Alisha Butler", title="Assistant Professor of Education Studies", url="https://www.wesleyan.edu/about/directory/profile.html?id=abutler", email="abutler@wesleyan.edu"),
            faculty("Katja Kolcio", title="Associate Professor", url="https://www.wesleyan.edu/about/directory/profile.html?id=kkolcio", email="kkolcio@wesleyan.edu"),
        ]),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
