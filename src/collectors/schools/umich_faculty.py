"""University of Michigan faculty config (via the faculty_graph engine).

Michigan's department directories are Cloudflare-protected (403 to a stdlib
scraper), so this began as a hand-verified seed set. It now runs the engine's
two-layer model: the curated seed is the always-on, offline-safe floor, and a
best-effort **render-mode scrape** (headless Chromium clears the 403, the same
trick Princeton uses) discovers the *full* department roster on top of it in
deep mode. Seed and scrape de-dup by id (dept+name) / email / URL, so the
hand-verified professors keep their curated keywords and the scrape only adds
net-new faculty; a failed scrape degrades silently to the seed.

Fourteen departments (~100 curated seeds; the deep scrape lifts the reachable
ones to their full rosters — e.g. Physics 7→51, Math 8→84, ME 8→106, ECE 8→111).
One source ("umich_faculty") across all of them (the UIUC model); the
department rides on each record's `department` field, and ids are namespaced
by department short-code so they never collide.

Scrape coverage (selectors verified live via headless render, Jul 2026):
  * LSA departments (lsa.umich.edu, "Michigan LSA" AEM theme) — Physics, Math,
    Chemistry, MCDB, Statistics, EEB, Economics, Psychology. Ship emailed +
    research-tag-keyworded.
  * Engineering (*.engin.umich.edu WordPress theme) — Mechanical Engineering
    (.faculty-row) and ECE (the shared "eecs_person" template, names "Last,
    First"). Ship emailed; keywords mined from the free-text interests block.
  * No scrape yet (curated-seed-only): CSE (cse.umich.edu refuses connections),
    Robotics (data-attribute cards, no listing email), BME & Aerospace (their
    directory URLs 404 — the seed's directory_url is the human landing page).
    Coverage grows here as reachable directories are identified.

Seed data verified Jun 2026 from lab/personal sites, Google Scholar, dblp, and
department news. Emails left as None where the uniqname could not be confirmed —
never guessed. Two distinct professors named "Wei Lu" (ECE/memristors vs
ME/batteries) are intentionally kept separate — the engine de-dups on
email/URL, not name.
"""

from __future__ import annotations

from .. import faculty_graph
from ..faculty_graph import faculty

# ---- Live-scrape selectors (deep mode; verified via headless render Jul 2026) ---
# All Michigan directories are Cloudflare-walled, so every scrape runs in render
# mode. Keep ladder faculty (the PIs an undergraduate would research with); the
# directories also list lecturers, research scientists, and emeriti.
_LADDER = {"require": r"\bprofessor\b", "drop": r"\bemerit"}

# lsa.umich.edu "Michigan LSA" AEM theme: a ``.person`` card grid. ``.name`` +
# ``.title`` carry name/rank, ``.email a`` the public umich address, and
# ``.fields a`` the research-area tags (clean atomic keywords, one <a> each).
_LSA_SELECTORS = {
    "card": ".person",
    "name": ".name",
    "link": ".name a",
    "title": ".title",
    "email": ".email a[href^='mailto:']",
    "research_items": ".fields a",
}

# College of Engineering WordPress theme (*.engin.umich.edu): ``.faculty-row``
# cards with ``.faculty-name`` / ``.faculty-titles`` / ``.faculty-email`` and a
# free-text ``.faculty-interests`` ("Research Interests: …") the engine mines
# for keywords at normalize time.
_ENGIN_SELECTORS = {
    "card": ".faculty-row",
    "name": ".faculty-name",
    "link": ".faculty-name a",
    "title": ".faculty-titles",
    "email": ".faculty-email",
    "research": ".faculty-interests",
}

# EECS (ece.engin.umich.edu) shared "eecs_person" template: names are listed
# "Last, First" (needs name_flip), rank rides ``.person_title_section``, the
# mailto ``.person_email``, and the research interests the ``.pcs_tall`` block.
_EECS_SELECTORS = {
    "card": ".eecs_person_wrapper",
    "name": ".eecs_person_name",
    "title": ".person_title_section",
    "email": ".person_email",
    "research": ".pcs_tall",
}


# Several LSA people grids (Chemistry, Psychology, Statistics, MCDB) render only
# 12 cards per page behind a client-side hash router — the rest load as the URL
# fragment changes to ``#…&page=N``. Physics/Math/Economics/EEB list everyone on
# one page, so they omit this. Walked in one render session by the engine's
# hash-paginate path (dedup by name+url).
_LSA_PAGINATE = {"mode": "hash", "param": "page", "max": 12}


def _scrape(url: str, selectors: dict, *, name_flip: bool = False,
            paginate: dict | None = None) -> dict:
    """A render-mode scrape block for a Cloudflare-walled Michigan directory."""
    block = {"url": url, "render": True, "selectors": selectors,
             "ladder_filter": _LADDER}
    if name_flip:
        block["name_flip"] = True
    if paginate:
        block["paginate"] = paginate
    return block

SCHOOL: dict = {
    "school_slug": "umich",
    "source": "umich_faculty",
    "organization": "University of Michigan",
    "location": "Ann Arbor, MI",
    "id_prefix": "umich",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Michigan) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        {
            "short": "CSE",
            "name": "Computer Science & Engineering",
            "majors": ["Computer Science", "Computer Engineering", "Data Science"],
            "directory_url": "https://cse.umich.edu/people/faculty/",
            "faculty": [
                faculty(
                    "Satinder Singh", title="Professor",
                    url="https://web.eecs.umich.edu/~baveja/",
                    research_areas="reinforcement learning, multi-agent learning, computational game theory, sequential decision-making",
                    keywords=["reinforcement learning", "multi-agent systems", "game theory", "sequential decision-making"],
                ),
                faculty(
                    "Jenna Wiens", title="Associate Professor",
                    url="https://wiens-group.engin.umich.edu/", email="wiensj@umich.edu",
                    research_areas="machine learning for healthcare, clinical time-series analysis, causal inference, transfer learning",
                    keywords=["machine learning", "healthcare", "clinical informatics", "causal inference"],
                ),
                faculty(
                    "Rada Mihalcea", title="Professor",
                    url="https://web.eecs.umich.edu/~mihalcea/", email="mihalcea@umich.edu",
                    research_areas="natural language processing, computational social science, multimodal processing, AI for social good",
                    keywords=["natural language processing", "computational social science", "multimodal learning", "ai for social good"],
                ),
                faculty(
                    "Michael Wellman", title="Professor",
                    url="https://strategicreasoning.org/", email="wellman@umich.edu",
                    research_areas="multiagent systems, game theory, empirical game-theoretic analysis, agent-based modeling, computational markets",
                    keywords=["multiagent systems", "game theory", "agent-based modeling", "computational markets"],
                ),
                faculty(
                    "Honglak Lee", title="Professor",
                    url="https://web.eecs.umich.edu/~honglak/", email="honglak@umich.edu",
                    research_areas="deep learning, representation learning, computer vision, reinforcement learning",
                    keywords=["deep learning", "representation learning", "computer vision", "reinforcement learning"],
                ),
                faculty(
                    "Emily Mower Provost", title="Professor",
                    url="https://emp.engin.umich.edu/", email="emilykmp@umich.edu",
                    research_areas="affective computing, speech and emotion recognition, machine learning for mental health, human-centered AI",
                    keywords=["affective computing", "speech recognition", "machine learning", "human-centered ai"],
                ),
                faculty(
                    "Justin Johnson", title="Assistant Professor",
                    url="https://web.eecs.umich.edu/~justincj/", email="justincj@umich.edu",
                    research_areas="computer vision, deep learning, vision and language, image generation, visual reasoning",
                    keywords=["computer vision", "deep learning", "vision and language", "image generation"],
                ),
                faculty(
                    "H.V. Jagadish", title="Professor",
                    url="https://web.eecs.umich.edu/~jag/", email="jag@umich.edu",
                    research_areas="databases, big data, data mining, data science, bioinformatics",
                    keywords=["databases", "big data", "data mining", "data science", "bioinformatics"],
                ),
            ],
        },
        {
            "short": "ECE",
            "name": "Electrical & Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering", "Electrical & Computer Engineering"],
            "directory_url": "https://ece.engin.umich.edu/people/faculty/",
            "scrape": _scrape("https://ece.engin.umich.edu/people/faculty/", _EECS_SELECTORS, name_flip=True),
            "faculty": [
                faculty(
                    "Alfred O. Hero III", title="Professor",
                    url="https://eecs.engin.umich.edu/people/hero-alfred/", email="hero@umich.edu",
                    research_areas="statistical signal and image processing, statistical machine learning, data science, sensor networks, bioinformatics",
                    keywords=["statistical signal processing", "machine learning", "data science", "sensor networks"],
                ),
                faculty(
                    "David Blaauw", title="Professor",
                    url="https://eecs.engin.umich.edu/people/blaauw-david/", email="blaauw@umich.edu",
                    research_areas="ultra-low-power VLSI, millimeter-scale computing, subthreshold design, mixed-signal circuits, embedded sensors",
                    keywords=["low-power vlsi", "millimeter-scale computing", "mixed-signal circuits", "embedded systems"],
                ),
                faculty(
                    "Dennis Sylvester", title="Professor",
                    url="https://eecs.engin.umich.edu/people/sylvester-dennis/",
                    research_areas="ultra-low-power IC design, VLSI CAD, machine-learning hardware accelerators, cryo-CMOS, hardware security",
                    keywords=["low-power circuits", "vlsi", "hardware accelerators", "hardware security"],
                ),
                faculty(
                    "Zhengya Zhang", title="Professor",
                    url="https://eecs.engin.umich.edu/people/zhang-zhengya/", email="zhengya@umich.edu",
                    research_areas="low-power VLSI, hardware for machine learning, DSP design, error-correction coding",
                    keywords=["vlsi", "hardware for machine learning", "signal processing", "error-correction coding"],
                ),
                faculty(
                    "Wei Lu", title="Professor",
                    url="https://public.websites.umich.edu/~wluee/", email="wluee@umich.edu",
                    research_areas="memristors, in-memory and neuromorphic computing, AI hardware, nanoelectronics",
                    keywords=["memristors", "neuromorphic computing", "ai hardware", "nanoelectronics"],
                ),
                faculty(
                    "Khalil Najafi", title="Professor",
                    url="https://eecs.engin.umich.edu/people/najafi-khalil/", email="najafi@umich.edu",
                    research_areas="MEMS, micromachined sensors, inertial sensors, implantable biomedical microsystems, energy harvesting",
                    keywords=["mems", "sensors", "biomedical microsystems", "energy harvesting"],
                ),
                faculty(
                    "Euisik Yoon", title="Professor",
                    url="https://eecs.engin.umich.edu/people/yoon-euisik/", email="esyoon@umich.edu",
                    research_areas="BioMEMS, lab-on-chip, MEMS neural interfaces, CMOS imaging, microfluidics",
                    keywords=["biomems", "lab-on-chip", "neural interfaces", "microfluidics"],
                ),
                faculty(
                    "Theodore B. Norris", title="Professor",
                    url="https://eecs.engin.umich.edu/people/norris-theodore-b/",
                    research_areas="ultrafast optics, terahertz generation and detection, plasmonics, optoelectronic measurement, biological imaging",
                    keywords=["ultrafast optics", "terahertz", "plasmonics", "biological imaging"],
                ),
            ],
        },
        {
            "short": "ME",
            "name": "Mechanical Engineering",
            "majors": ["Mechanical Engineering"],
            "directory_url": "https://me.engin.umich.edu/people/faculty/",
            "scrape": _scrape("https://me.engin.umich.edu/people/faculty/", _ENGIN_SELECTORS),
            "faculty": [
                faculty(
                    "Jeff Sakamoto", title="Professor",
                    url="https://sakamoto.engin.umich.edu/",
                    research_areas="solid-state batteries, ceramic electrolytes, electrochemistry-mechanics coupling, battery manufacturing",
                    keywords=["solid-state batteries", "ceramic electrolytes", "electrochemistry", "energy storage"],
                ),
                faculty(
                    "Wei Lu", title="Professor",
                    url="https://lu.engin.umich.edu/", email="weilu@umich.edu",
                    research_areas="lithium-ion battery modeling, energy storage, microstructure simulation, multiphysics mechanics of materials, advanced manufacturing",
                    keywords=["battery modeling", "energy storage", "multiphysics simulation", "advanced manufacturing"],
                ),
                faculty(
                    "Margaret Wooldridge", title="Professor",
                    url="https://wooldridge.engin.umich.edu/",
                    research_areas="combustion chemistry, biofuels, engine efficiency, reaction kinetics, optical combustion diagnostics",
                    keywords=["combustion", "biofuels", "reaction kinetics", "sustainable energy"],
                ),
                faculty(
                    "Ellen M. Arruda", title="Professor",
                    url="https://arruda.engin.umich.edu/",
                    research_areas="polymer mechanics, soft tissue biomechanics, tissue engineering, polymer nanocomposites",
                    keywords=["polymer mechanics", "biomechanics", "tissue engineering", "nanocomposites"],
                ),
                faculty(
                    "Eric Johnsen", title="Professor",
                    url="https://public.websites.umich.edu/~ejohnsen/home.html",
                    research_areas="computational fluid dynamics, multiphase flow, cavitation, shock waves, turbulence, high-performance computing",
                    keywords=["computational fluid dynamics", "multiphase flow", "turbulence", "high-performance computing"],
                ),
                faculty(
                    "Kira Barton", title="Professor",
                    url="https://brg.engin.umich.edu/",
                    research_areas="iterative learning control, precision motion control, smart additive manufacturing, multi-agent robotics",
                    keywords=["control systems", "precision motion control", "additive manufacturing", "robotics"],
                ),
                faculty(
                    "Ramanarayan Vasudevan", title="Associate Professor",
                    url="https://me.engin.umich.edu/people/faculty/ramanarayan-vasudevan/",
                    research_areas="legged robot control, motion planning, safe planning under uncertainty, nonlinear dynamics, autonomous vehicles",
                    keywords=["robotics", "motion planning", "autonomous vehicles", "control systems"],
                ),
                faculty(
                    "Daniel Bruder", title="Assistant Professor",
                    url="https://danielbruder.com/", email="bruderd@umich.edu",
                    research_areas="soft robotics, robot dynamics and controls, data-driven modeling of soft systems",
                    keywords=["soft robotics", "robot control", "data-driven modeling"],
                ),
            ],
        },
        {
            "short": "PHYS",
            "name": "Department of Physics",
            "majors": ["Physics", "Applied Physics", "Astrophysics"],
            "directory_url": "https://lsa.umich.edu/physics/people/faculty.html",
            "scrape": _scrape("https://lsa.umich.edu/physics/people/faculty.html", _LSA_SELECTORS),
            "faculty": [
                faculty(
                    "Dragan Huterer", title="Professor",
                    url="https://public.websites.umich.edu/~huterer/", email="huterer@umich.edu",
                    research_areas="theoretical cosmology, dark energy, dark matter, cosmic large-scale structure, gravitational lensing",
                    keywords=["cosmology", "dark energy", "dark matter", "gravitational lensing"],
                ),
                faculty(
                    "Kai Sun", title="Professor",
                    url="https://sites.lsa.umich.edu/kai-sun/",
                    research_areas="condensed matter theory, topological phases, moire materials, many-body physics, ultracold atomic gases",
                    keywords=["condensed matter theory", "topological phases", "moire materials", "many-body physics"],
                ),
                faculty(
                    "Georg Raithel", title="Professor",
                    url="https://lsa.umich.edu/physics/people/faculty/graithel.html",
                    research_areas="Rydberg atoms, precision spectroscopy, quantum information, electric-field sensing, atomic molecular and optical physics",
                    keywords=["rydberg atoms", "quantum information", "precision spectroscopy", "atomic physics"],
                ),
                faculty(
                    "Alexander Kuzmich", title="Professor",
                    url="https://sites.lsa.umich.edu/kuzmich-lab/",
                    research_areas="ultracold atomic physics, quantum optics, quantum information, quantum memories, Rydberg interactions",
                    keywords=["ultracold atoms", "quantum optics", "quantum information", "quantum memories"],
                ),
                faculty(
                    "Aaron Pierce", title="Professor",
                    url="https://lsa.umich.edu/physics/people/faculty/atpierce.html",
                    research_areas="theoretical particle physics, beyond-Standard-Model physics, dark matter, baryogenesis, particle cosmology",
                    keywords=["particle physics", "beyond standard model", "dark matter", "particle cosmology"],
                ),
                faculty(
                    "Keith Riles", title="Professor",
                    url="https://gallatin.physics.lsa.umich.edu/~keithr/",
                    research_areas="gravitational-wave detection, LIGO, continuous-wave searches, experimental astrophysics, data analysis",
                    keywords=["gravitational waves", "ligo", "experimental astrophysics", "data analysis"],
                ),
                faculty(
                    "Junjie Zhu", title="Professor",
                    url="https://sites.google.com/umich.edu/junjiezhu", email="junjie@umich.edu",
                    research_areas="experimental particle physics, ATLAS, Higgs boson measurements, electroweak physics, detector electronics",
                    keywords=["particle physics", "atlas experiment", "higgs boson", "detector instrumentation"],
                ),
            ],
        },
        {
            "short": "MCDB",
            "name": "Molecular, Cellular & Developmental Biology",
            "majors": ["Molecular Biology", "Cellular Biology", "Biology", "Biochemistry"],
            "directory_url": "https://lsa.umich.edu/mcdb/people/faculty.html",
            "scrape": _scrape("https://lsa.umich.edu/mcdb/people/faculty.html", _LSA_SELECTORS, paginate=_LSA_PAGINATE),
            "faculty": [
                faculty(
                    "Kenneth Cadigan", title="Professor",
                    url="https://sites.lsa.umich.edu/cadigan-lab/", email="cadigan@umich.edu",
                    research_areas="Wnt signal transduction, transcriptional regulation, Drosophila developmental genetics, cell signaling",
                    keywords=["cell signaling", "wnt signaling", "developmental genetics", "transcription"],
                ),
                faculty(
                    "Monica Dus", title="Associate Professor",
                    url="https://www.monicadus.com/", email="mdus@umich.edu",
                    research_areas="molecular nutrition, nutrigenomics, diet-gene interactions, feeding behavior, neural plasticity",
                    keywords=["nutrigenomics", "molecular nutrition", "neural plasticity", "feeding behavior"],
                ),
                faculty(
                    "Ursula Jakob", title="Professor",
                    url="https://sites.lsa.umich.edu/jakob-lab/",
                    research_areas="oxidative stress, redox regulation, reactive oxygen species in aging, cellular stress responses, molecular chaperones",
                    keywords=["oxidative stress", "redox regulation", "aging", "molecular chaperones"],
                ),
                faculty(
                    "Patricia Wittkopp", title="Professor",
                    url="https://sites.lsa.umich.edu/wittkopp-lab/",
                    research_areas="evolution of gene expression, regulatory evolution, cis-regulatory variation, Drosophila pigmentation, phenotypic divergence",
                    keywords=["gene regulation", "evolutionary genetics", "gene expression", "drosophila genetics"],
                ),
                faculty(
                    "Matthew Chapman", title="Professor",
                    url="https://sites.lsa.umich.edu/chapman-lab/", email="chapmanm@umich.edu",
                    research_areas="functional bacterial amyloids, biofilm formation, amyloid assembly, links to neurodegenerative disease",
                    keywords=["microbiology", "bacterial amyloids", "biofilms", "protein aggregation"],
                ),
                faculty(
                    "Cunming Duan", title="Professor",
                    url="https://lsa.umich.edu/mcdb/people/faculty/cunming-duan.html",
                    research_areas="insulin-like growth factor signaling, peptide growth factors, vertebrate development, zebrafish models",
                    keywords=["cell signaling", "growth factors", "developmental biology", "zebrafish"],
                ),
                faculty(
                    "Yanzhuang Wang", title="Professor",
                    url="https://lsa.umich.edu/mcdb/people/faculty/yzwang.html",
                    research_areas="Golgi apparatus biogenesis, membrane stacking, mitosis, Golgi defects in cancer and Alzheimer's",
                    keywords=["cell biology", "golgi apparatus", "membrane trafficking", "mitosis"],
                ),
                faculty(
                    "Catherine Collins", title="Professor",
                    url="https://sites.lsa.umich.edu/collins-lab/",
                    research_areas="axon injury and regeneration, DLK signaling in nerve repair, neuronal plasticity, Drosophila models",
                    keywords=["neuroscience", "axon regeneration", "neuronal signaling", "drosophila genetics"],
                ),
            ],
        },
        {
            "short": "STATS",
            "name": "Department of Statistics",
            "majors": ["Statistics", "Data Science"],
            "directory_url": "https://lsa.umich.edu/stats/people/faculty.html",
            "scrape": _scrape("https://lsa.umich.edu/stats/people/faculty.html", _LSA_SELECTORS, paginate=_LSA_PAGINATE),
            "faculty": [
                faculty(
                    "Ji Zhu", title="Professor",
                    url="https://lsa.umich.edu/stats/people/faculty/jizhu.html", email="jizhu@umich.edu",
                    research_areas="statistical machine learning, high-dimensional data, statistical network analysis, health-science applications",
                    keywords=["statistical machine learning", "high-dimensional statistics", "network analysis"],
                ),
                faculty(
                    "Elizaveta Levina", title="Professor",
                    url="https://sites.google.com/umich.edu/elevina", email="elevina@umich.edu",
                    research_areas="network analysis, high-dimensional statistics, statistical learning, neuroscience and imaging applications",
                    keywords=["network analysis", "high-dimensional statistics", "statistical learning"],
                ),
                faculty(
                    "Ambuj Tewari", title="Professor",
                    url="https://www.ambujtewari.com/", email="tewaria@umich.edu",
                    research_areas="statistical learning theory, online learning, reinforcement learning, optimization for machine learning, mobile health",
                    keywords=["learning theory", "online learning", "reinforcement learning", "optimization"],
                ),
                faculty(
                    "XuanLong Nguyen", title="Professor",
                    url="https://dept.stat.lsa.umich.edu/~xuanlong/",
                    research_areas="Bayesian nonparametrics, mixture models, optimal transport, machine learning, spatiotemporal data",
                    keywords=["bayesian statistics", "optimal transport", "machine learning", "mixture models"],
                ),
                faculty(
                    "Edward Ionides", title="Professor",
                    url="https://ionides.github.io/",
                    research_areas="time series analysis, inference for partially observed Markov processes, statistical epidemiology, dynamic systems modeling",
                    keywords=["time series", "statistical epidemiology", "markov processes", "dynamic systems"],
                ),
                faculty(
                    "Gongjun Xu", title="Professor",
                    url="https://sites.google.com/umich.edu/gongjunxu",
                    research_areas="latent variable models, psychometrics, item response theory, high-dimensional inference, survival analysis",
                    keywords=["latent variable models", "psychometrics", "high-dimensional inference", "survival analysis"],
                ),
                faculty(
                    "Yang Chen", title="Associate Professor",
                    url="https://yangchenfunstatistics.github.io/yangchen.github.io/", email="ychenang@umich.edu",
                    research_areas="Bayesian modeling and computation, hidden Markov models, statistics in astronomy, spatiotemporal data, uncertainty quantification",
                    keywords=["bayesian statistics", "astrostatistics", "uncertainty quantification", "spatiotemporal data"],
                ),
                faculty(
                    "Yixin Wang", title="Assistant Professor",
                    url="https://yixinwang.github.io/", email="yixinw@umich.edu",
                    research_areas="Bayesian statistics, causal inference, machine learning, probabilistic generative modeling, recommender systems",
                    keywords=["bayesian statistics", "causal inference", "machine learning", "generative models"],
                ),
            ],
        },
        {
            "short": "BME",
            "name": "Biomedical Engineering",
            "majors": ["Biomedical Engineering"],
            "directory_url": "https://bme.umich.edu/people/faculty/",
            "faculty": [
                faculty(
                    "Lonnie Shea", title="Professor",
                    url="https://shearesearch.engin.umich.edu/", email="ldshea@umich.edu",
                    research_areas="regenerative medicine, gene and drug delivery, immunoengineering, biomaterials, islet transplantation",
                    keywords=["regenerative medicine", "drug delivery", "immunoengineering", "biomaterials"],
                ),
                faculty(
                    "Jan Stegemann", title="Professor",
                    url="https://macro.engin.umich.edu/profile/stegemann-jan/",
                    research_areas="biomaterials, tissue engineering, cell-based therapies, bone regeneration, extracellular matrix",
                    keywords=["biomaterials", "tissue engineering", "cell therapy", "bone regeneration"],
                ),
                faculty(
                    "Andrew Putnam", title="Professor",
                    url="https://www.theputnamlab.com/",
                    research_areas="tissue engineering, angiogenesis and vascularization, mechanobiology, extracellular matrix, regenerative medicine",
                    keywords=["tissue engineering", "angiogenesis", "mechanobiology", "regenerative medicine"],
                ),
                faculty(
                    "Mary-Ann Mycek", title="Professor",
                    url="https://lsa.umich.edu/appliedphysics/people/faculty/mycek.html",
                    research_areas="biomedical optics, optical tissue spectroscopy, non-invasive optical diagnostics, cancer detection, fluorescence lifetime imaging",
                    keywords=["biomedical optics", "biophotonics", "optical diagnostics", "cancer detection"],
                ),
                faculty(
                    "Joerg Lahann", title="Professor",
                    url="https://www.lahannlab.com/joerg-lahann",
                    research_areas="polymer surface coatings, advanced biomaterials, nanoparticle drug and gene delivery, engineered microenvironments, biomimetic materials",
                    keywords=["biomaterials", "polymer coatings", "drug delivery", "biomimetic materials"],
                ),
                faculty(
                    "Nicholas Kotov", title="Professor",
                    url="https://kotov.engin.umich.edu/",
                    research_areas="biomimetic nanostructures, chiral nanomaterials, nanoparticle self-assembly, nanocomposites, biosensing",
                    keywords=["nanomaterials", "self-assembly", "nanocomposites", "biosensing"],
                ),
                faculty(
                    "Rhima Coleman", title="Associate Professor",
                    url="https://www.researchgate.net/profile/Rhima-Coleman",
                    research_areas="cartilage tissue engineering, cartilage regeneration, joint mechanobiology, chondrogenesis, mechanically functional tissue replacement",
                    keywords=["tissue engineering", "cartilage regeneration", "mechanobiology", "chondrogenesis"],
                ),
                faculty(
                    "Carlos Aguilar", title="Associate Professor",
                    url="https://bme.umich.edu/people/carlos-aguilar/", email="caguilar@umich.edu",
                    research_areas="BioMEMS, microfluidics, bio-micro/nano systems, nanotechnology",
                    keywords=["BioMEMS", "microfluidics", "bio-micro/nano systems", "nanotechnology"],
                ),
                faculty(
                    "Kelly Arnold", title="Associate Professor",
                    url="https://bme.umich.edu/people/arnold-kelly/", email="kbarnold@umich.edu",
                    research_areas="computational modeling, drug delivery, therapeutics",
                    keywords=["computational modeling", "drug delivery", "therapeutics"],
                ),
                faculty(
                    "Brendon Baker", title="Associate Professor",
                    url="https://bme.umich.edu/people/baker-brendon/", email="bambren@umich.edu",
                    research_areas="BioMEMS, microfluidics, bio-micro/nano systems, biomaterials",
                    keywords=["BioMEMS", "microfluidics", "bio-micro/nano systems", "biomaterials"],
                ),
                faculty(
                    "Susan Brooks", title="Professor",
                    url="https://bme.umich.edu/people/brooks-susan/", email="svbrooks@umich.edu",
                    research_areas="biomechanics, immunoengineering, molecular & cellular engineering, orthopaedic engineering",
                    keywords=["biomechanics", "immunoengineering", "molecular & cellular engineering", "orthopaedic engineering"],
                ),
                faculty(
                    "Tim Bruns", title="Associate Professor",
                    url="https://bme.umich.edu/people/bruns-tim/", email="bruns@umich.edu",
                    research_areas="neural engineering, neurological disorders",
                    keywords=["neural engineering", "neurological disorders"],
                ),
                faculty(
                    "Sriram Chandrasekaran", title="Associate Professor",
                    url="https://bme.umich.edu/people/chandrasekaran-sriram/", email="csriram@umich.edu",
                    research_areas="computational modeling, cancer, drug delivery, therapeutics",
                    keywords=["computational modeling", "cancer", "drug delivery", "therapeutics"],
                ),
                faculty(
                    "Cindy Chestek", title="Professor",
                    url="https://bme.umich.edu/people/chestek-cindy/", email="cchestek@umich.edu",
                    research_areas="BioMEMS, microfluidics, bio-micro/nano systems, neural engineering",
                    keywords=["BioMEMS", "microfluidics", "bio-micro/nano systems", "neural engineering"],
                ),
                faculty(
                    "María Coronel", title="Assistant Professor",
                    url="https://bme.umich.edu/people/coronel-maria/", email="mcoronel@umich.edu",
                    research_areas="biomaterials, drug delivery, therapeutics, immunoengineering",
                    keywords=["biomaterials", "drug delivery", "therapeutics", "immunoengineering"],
                ),
                faculty(
                    "Anne Draelos", title="Assistant Professor",
                    url="https://bme.umich.edu/people/draelos-anne/", email="adraelos@umich.edu",
                    research_areas="computational modeling, neural engineering, neurological disorders",
                    keywords=["computational modeling", "neural engineering", "neurological disorders"],
                ),
                faculty(
                    "Xudong (Sherman) Fan", title="Professor",
                    url="https://bme.umich.edu/people/fan-xudong/", email="xsfan@umich.edu",
                    research_areas="BioMEMS, microfluidics, bio-micro/nano systems, biomedical imaging",
                    keywords=["BioMEMS", "microfluidics", "bio-micro/nano systems", "biomedical imaging"],
                ),
                faculty(
                    "Jonathan Fay", title="Associate Professor",
                    url="https://bme.umich.edu/people/fay-jonathan/", email="jpfay@umich.edu",
                    research_areas="biomechanics, biomedical innovation, engineering education",
                    keywords=["biomechanics", "biomedical innovation", "engineering education"],
                ),
                faculty(
                    "C. Alberto Figueroa", title="Professor",
                    url="https://bme.umich.edu/people/figueroa-c-alberto/", email="figueroc@med.umich.edu",
                    research_areas="biofluid mechanics, biomechanics, biomedical AI, computational modeling",
                    keywords=["biofluid mechanics", "biomechanics", "biomedical AI", "computational modeling"],
                ),
                faculty(
                    "James Grotberg", title="Professor",
                    url="https://bme.umich.edu/people/grotberg-james/", email="grotberg@umich.edu",
                    research_areas="artificial organs, biofluid mechanics, biomechanics, computational modeling",
                    keywords=["artificial organs", "biofluid mechanics", "biomechanics", "computational modeling"],
                ),
                faculty(
                    "Karin Jensen", title="Assistant Professor",
                    url="https://bme.umich.edu/people/jensen-karin/", email="kjens@umich.edu",
                    research_areas="engineering education",
                    keywords=["engineering education"],
                ),
                faculty(
                    "Paul Jensen", title="Associate Professor",
                    url="https://bme.umich.edu/people/jensen-paul/", email="pjens@umich.edu",
                    research_areas="BioMEMS, microfluidics, biomedical AI, computational modeling",
                    keywords=["BioMEMS", "microfluidics", "biomedical AI", "computational modeling"],
                ),
                faculty(
                    "David Kohn", title="Professor",
                    url="https://bme.umich.edu/people/kohn-david/", email="dhkohn@umich.edu",
                    research_areas="biomaterials, biomechanics, drug delivery, therapeutics",
                    keywords=["biomaterials", "biomechanics", "drug delivery", "therapeutics"],
                ),
                faculty(
                    "Scott Lempka", title="Associate Professor",
                    url="https://bme.umich.edu/people/lempka-scott/", email="lempka@umich.edu",
                    research_areas="computational modeling, neural engineering",
                    keywords=["computational modeling", "neural engineering"],
                ),
                faculty(
                    "Jiahe Li", title="Assistant Professor",
                    url="https://bme.umich.edu/people/li-jiahe/", email="jiaheli@umich.edu",
                    research_areas="bio-micro/nano systems, cancer, drug delivery, therapeutics",
                    keywords=["bio-micro/nano systems", "cancer", "drug delivery", "therapeutics"],
                ),
                faculty(
                    "Zhongming Liu", title="Associate Professor",
                    url="https://bme.umich.edu/people/liu-zhongming/", email="zmliu@umich.edu",
                    research_areas="computational modeling, biomedical imaging, biophotonics, neural engineering",
                    keywords=["computational modeling", "biomedical imaging", "biophotonics", "neural engineering"],
                ),
                faculty(
                    "Brian Love", title="Professor",
                    url="https://bme.umich.edu/people/love-brian/", email="bjlove@umich.edu",
                    research_areas="biomaterials, biomechanics, cardiovascular engineering, molecular & cellular engineering",
                    keywords=["biomaterials", "biomechanics", "cardiovascular engineering", "molecular & cellular engineering"],
                ),
                faculty(
                    "Chima Maduka", title="Assistant Professor",
                    url="https://bme.umich.edu/people/chima-maduka-ph-d/", email="madukach@umich.edu",
                    research_areas="bio-micro/nano systems, cardiovascular engineering, drug delivery, therapeutics",
                    keywords=["bio-micro/nano systems", "cardiovascular engineering", "drug delivery", "therapeutics"],
                ),
                faculty(
                    "Geeta Mehta", title="Associate Professor",
                    url="https://bme.umich.edu/people/mehta-geeta/", email="mehtagee@umich.edu",
                    research_areas="BioMEMS, microfluidics, bio-micro/nano systems, biomaterials",
                    keywords=["BioMEMS", "microfluidics", "bio-micro/nano systems", "biomaterials"],
                ),
                faculty(
                    "Aaron Morris", title="Assistant Professor",
                    url="https://bme.umich.edu/people/aaron-morris/", email="aharmorr@umich.edu",
                    research_areas="bio-micro/nano systems, biomaterials, computational modeling, cancer",
                    keywords=["bio-micro/nano systems", "biomaterials", "computational modeling", "cancer"],
                ),
                faculty(
                    "Deepak Nagrath", title="Professor",
                    url="https://bme.umich.edu/people/nagrath-deepak/", email="dnagrath@umich.edu",
                    research_areas="computational modeling, tissue engineering, biomaterials, regenerative medicine",
                    keywords=["computational modeling", "tissue engineering", "biomaterials", "regenerative medicine"],
                ),
                faculty(
                    "Douglas Noll", title="Professor",
                    url="https://bme.umich.edu/people/noll-douglas/", email="dnoll@umich.edu",
                    research_areas="biomedical imaging, biophotonics, molecular imaging, neurological disorders",
                    keywords=["biomedical imaging", "biophotonics", "molecular imaging", "neurological disorders"],
                ),
                faculty(
                    "David Nordsletten", title="Professor",
                    url="https://bme.umich.edu/people/nordsletten-david/", email="nordslet@umich.edu",
                    research_areas="biofluid mechanics, biomechanics, computational modeling, biomedical imaging",
                    keywords=["biofluid mechanics", "biomechanics", "computational modeling", "biomedical imaging"],
                ),
                faculty(
                    "Enrico Opri", title="Assistant Professor",
                    url="https://bme.umich.edu/people/opri-enrico/", email="eopri@umich.edu",
                    research_areas="computational modeling, neural engineering",
                    keywords=["computational modeling", "neural engineering"],
                ),
            ],
        },
        {
            "short": "ROB",
            "name": "Robotics",
            "majors": ["Robotics", "Computer Science", "Electrical Engineering", "Mechanical Engineering"],
            "directory_url": "https://robotics.umich.edu/people/faculty/",
            "faculty": [
                faculty(
                    "Dmitry Berenson", title="Associate Professor",
                    url="https://berenson.robotics.umich.edu/", email="dmitryb@umich.edu",
                    research_areas="motion planning, robot manipulation, robot learning, optimization, deformable object manipulation",
                    keywords=["motion planning", "robot manipulation", "robot learning", "optimization"],
                ),
                faculty(
                    "Odest Chadwicke Jenkins", title="Professor",
                    url="https://web.eecs.umich.edu/~ocj/",
                    research_areas="robot learning from demonstration, robot perception, semantic mapping, human-robot interaction, manipulation",
                    keywords=["robot learning", "robot perception", "human-robot interaction", "manipulation"],
                ),
                faculty(
                    "Maani Ghaffari", title="Assistant Professor",
                    url="https://www.maanighaffari.com/", email="maanigj@umich.edu",
                    research_areas="robot perception, SLAM and navigation, motion planning on Lie groups, machine learning for robotics, planning under uncertainty",
                    keywords=["robot perception", "slam", "motion planning", "machine learning"],
                ),
                faculty(
                    "Nima Fazeli", title="Assistant Professor",
                    url="https://nima-fazeli.github.io/", email="nfz@umich.edu",
                    research_areas="robotic manipulation, tactile sensing, visuo-tactile representation learning, contact-rich modeling and control, model-based planning",
                    keywords=["robot manipulation", "tactile sensing", "representation learning", "control"],
                ),
                faculty(
                    "Katherine Skinner", title="Assistant Professor",
                    url="https://sites.google.com/umich.edu/kskin", email="kskin@umich.edu",
                    research_areas="marine and field robotics perception, computer vision, machine learning for autonomy, underwater 3D reconstruction, perception for autonomous vehicles",
                    keywords=["field robotics", "computer vision", "machine learning", "autonomy"],
                ),
                faculty(
                    "Talia Moore", title="Assistant Professor",
                    url="https://robotics.umich.edu/people/faculty/talia-moore/", email="taliaym@umich.edu",
                    research_areas="bio-inspired robotics, animal-robot interaction, legged and arrhythmic locomotion, soft robotics, evolution of motion",
                    keywords=["bio-inspired robotics", "legged locomotion", "soft robotics", "biomechanics"],
                ),
            ],
        },
        {
            "short": "CHEM",
            "name": "Department of Chemistry",
            "majors": ["Chemistry", "Biochemistry", "Chemical Biology"],
            "directory_url": "https://lsa.umich.edu/chem/people/faculty.html",
            "scrape": _scrape("https://lsa.umich.edu/chem/people/faculty.html", _LSA_SELECTORS, paginate=_LSA_PAGINATE),
            "faculty": [
                faculty(
                    "Melanie Sanford", title="Professor",
                    url="https://sites.lsa.umich.edu/msanford-lab/",
                    research_areas="catalytic C-H functionalization, transition-metal catalysis, oxidative difunctionalization, synthetic methodology",
                    keywords=["catalysis", "organic chemistry", "c-h functionalization", "synthesis"],
                ),
                faculty(
                    "Nicolai Lehnert", title="Professor",
                    url="https://websites.umich.edu/~lehnert/", email="lehnert@umich.edu",
                    research_areas="bioinorganic chemistry, nitric oxide coordination chemistry, metalloenzyme biocatalysis, homogeneous catalysis for energy conversion",
                    keywords=["bioinorganic chemistry", "inorganic chemistry", "catalysis", "spectroscopy"],
                ),
                faculty(
                    "John Montgomery", title="Professor",
                    url="https://sites.lsa.umich.edu/jmgroup/",
                    research_areas="nickel catalysis, reductive coupling and cyclization, C-H functionalization, transition-metal methodology, total synthesis",
                    keywords=["catalysis", "organic chemistry", "synthesis", "methodology"],
                ),
                faculty(
                    "Anne McNeil", title="Professor",
                    url="https://mcneilgroup.chem.lsa.umich.edu/",
                    research_areas="sustainable polymers, chemical recycling, conjugated polymers, PFAS adsorbents, redox-flow-battery materials",
                    keywords=["polymer chemistry", "sustainability", "materials chemistry", "chemical recycling"],
                ),
                faculty(
                    "Adam Matzger", title="Professor",
                    url="https://websites.umich.edu/~ajmgroup/",
                    research_areas="metal-organic frameworks, porous materials and gas storage, polymorphism, energetic cocrystals, organic materials",
                    keywords=["metal-organic frameworks", "porous materials", "materials chemistry", "crystallization"],
                ),
                faculty(
                    "Kerri Pratt", title="Professor",
                    url="https://sites.lsa.umich.edu/prattlab/", email="kapratt@umich.edu",
                    research_areas="atmospheric chemistry, aerosol and trace-gas chemistry, Arctic and polar chemistry, atmospheric mass spectrometry, halogen chemistry",
                    keywords=["atmospheric chemistry", "aerosols", "mass spectrometry", "polar chemistry"],
                ),
                faculty(
                    "Zhan Chen", title="Professor",
                    url="https://sites.lsa.umich.edu/zhanchen/", email="zhanc@umich.edu",
                    research_areas="sum-frequency-generation vibrational spectroscopy, buried polymer and protein interfaces, anti-biofouling biomaterials, interfacial molecular structure, biosensing",
                    keywords=["spectroscopy", "physical chemistry", "interfaces", "biosensing"],
                ),
            ],
        },
        {
            "short": "MATH",
            "name": "Department of Mathematics",
            "majors": ["Mathematics", "Applied Mathematics"],
            "directory_url": "https://lsa.umich.edu/math/people/faculty.html",
            "scrape": _scrape("https://lsa.umich.edu/math/people/faculty.html", _LSA_SELECTORS),
            "faculty": [
                faculty(
                    "Mircea Mustata", title="Professor",
                    url="https://dept.math.lsa.umich.edu/~mmustata/",
                    research_areas="algebraic geometry, singularities, birational geometry, Hodge ideals, jet schemes",
                    keywords=["algebraic geometry", "singularities", "birational geometry"],
                ),
                faculty(
                    "Karen E. Smith", title="Professor",
                    url="https://dept.math.lsa.umich.edu/~kesmith/",
                    research_areas="commutative algebra, algebraic geometry, tight closure theory, characteristic-p methods, singularities",
                    keywords=["commutative algebra", "algebraic geometry", "singularities"],
                ),
                faculty(
                    "Sarah C. Koch", title="Professor",
                    url="https://dept.math.lsa.umich.edu/~kochsc/",
                    research_areas="complex dynamics, complex analysis, Teichmuller theory, dynamical moduli spaces, dynamical systems",
                    keywords=["complex dynamics", "complex analysis", "dynamical systems"],
                ),
                faculty(
                    "Andrew Snowden", title="Professor",
                    url="https://dept.math.lsa.umich.edu/~asnowden/",
                    research_areas="representation stability, commutative algebra, representation theory, number theory, arithmetic geometry",
                    keywords=["representation theory", "commutative algebra", "number theory"],
                ),
                faculty(
                    "Tasho Kaletha", title="Professor",
                    url="https://dept.math.lsa.umich.edu/~kaletha/",
                    research_areas="Langlands program, representation theory of p-adic groups, local Langlands correspondence, harmonic analysis on reductive groups",
                    keywords=["langlands program", "representation theory", "harmonic analysis"],
                ),
                faculty(
                    "Ralf J. Spatzier", title="Professor",
                    url="https://dept.math.lsa.umich.edu/~spatzier/",
                    research_areas="dynamical systems, ergodic theory, differential geometry, rigidity theory, hyperbolic group actions",
                    keywords=["dynamical systems", "ergodic theory", "differential geometry"],
                ),
                faculty(
                    "Jeffrey C. Lagarias", title="Professor",
                    url="https://dept.math.lsa.umich.edu/~lagarias/",
                    research_areas="number theory, harmonic analysis, ergodic theory, low-dimensional topology, discrete mathematics",
                    keywords=["number theory", "harmonic analysis", "discrete mathematics"],
                ),
                faculty(
                    "Wei Ho", title="Professor",
                    url="https://dept.math.lsa.umich.edu/~weiho/",
                    research_areas="number theory, arithmetic geometry, algebraic geometry, arithmetic statistics, representation theory",
                    keywords=["number theory", "arithmetic geometry", "algebraic geometry"],
                ),
            ],
        },
        {
            "short": "EEB",
            "name": "Ecology & Evolutionary Biology",
            "majors": ["Ecology and Evolutionary Biology", "Biology", "Environmental Science"],
            "directory_url": "https://lsa.umich.edu/eeb/people/faculty.html",
            "scrape": _scrape("https://lsa.umich.edu/eeb/people/faculty.html", _LSA_SELECTORS),
            "faculty": [
                faculty(
                    "Meghan Duffy", title="Professor",
                    url="https://duffylab.wordpress.com/", email="duffymeg@umich.edu",
                    research_areas="disease ecology, host-parasite interactions, freshwater ecology, Daphnia population biology, evolution of infectious disease",
                    keywords=["disease ecology", "freshwater ecology", "host-parasite interactions", "population biology"],
                ),
                faculty(
                    "Vincent Denef", title="Associate Professor",
                    url="https://websites.umich.edu/~vdenef/index.htm",
                    research_areas="freshwater microbial ecology, microbial community genomics, metagenomics, host-microbiome interactions, Great Lakes plankton",
                    keywords=["microbial ecology", "metagenomics", "microbiome", "freshwater ecology"],
                ),
                faculty(
                    "Stephen A. Smith", title="Associate Professor",
                    url="http://blackrim.org/",
                    research_areas="phylogenetics, plant evolution, computational tree-of-life methods, macroevolution from genomes and transcriptomes, evolutionary rates",
                    keywords=["phylogenetics", "plant evolution", "macroevolution", "computational biology"],
                ),
                faculty(
                    "Alison Davis Rabosky", title="Associate Professor",
                    url="https://websites.umich.edu/~ardr/",
                    research_areas="evolution of mimicry, reptile and snake systematics, color polymorphism, phenotypic novelty, comparative genomics",
                    keywords=["evolutionary biology", "herpetology", "systematics", "comparative genomics"],
                ),
                faculty(
                    "Daniel Rabosky", title="Professor",
                    url="https://websites.umich.edu/~drabosky/",
                    research_areas="macroevolution, speciation and extinction dynamics, phylogenetic comparative methods, fish and reptile diversification, paleobiology",
                    keywords=["macroevolution", "speciation", "phylogenetics", "biodiversity"],
                ),
                faculty(
                    "Jianzhi Zhang", title="Professor",
                    url="https://websites.umich.edu/~zhanglab/", email="jianzhi@umich.edu",
                    research_areas="molecular evolution, evolutionary genetics, evolutionary systems biology, yeast functional genomics, chance versus necessity in evolution",
                    keywords=["molecular evolution", "evolutionary genetics", "functional genomics", "systems biology"],
                ),
                faculty(
                    "Timothy James", title="Professor",
                    url="https://sites.lsa.umich.edu/mycology/",
                    research_areas="mycology, fungal evolution and genetics, fungal phylogeny and biodiversity, evolution of mating systems, chytrid biology",
                    keywords=["mycology", "fungal evolution", "phylogeny", "biodiversity"],
                ),
            ],
        },
        {
            "short": "ECON",
            "name": "Department of Economics",
            "majors": ["Economics"],
            "directory_url": "https://lsa.umich.edu/econ/people/faculty.html",
            "scrape": _scrape("https://lsa.umich.edu/econ/people/faculty.html", _LSA_SELECTORS),
            "faculty": [
                faculty(
                    "Justin Wolfers", title="Professor",
                    url="https://sites.google.com/site/jwolfers/",
                    research_areas="labor economics, macroeconomics, economics of well-being, economics of the family, prediction markets",
                    keywords=["labor economics", "macroeconomics", "applied economics"],
                ),
                faculty(
                    "Betsey Stevenson", title="Professor",
                    url="http://users.nber.org/~bstevens/aboutme.php",
                    research_areas="labor economics, women's labor-market outcomes, economics of the family, subjective well-being",
                    keywords=["labor economics", "economics of the family", "applied microeconomics"],
                ),
                faculty(
                    "Matthew D. Shapiro", title="Professor",
                    url="https://sites.lsa.umich.edu/shapiro/",
                    research_areas="macroeconomics, big data in economics, household saving and retirement decisions, measurement of economic statistics",
                    keywords=["macroeconomics", "household finance", "economic measurement"],
                ),
                faculty(
                    "Hoyt Bleakley", title="Associate Professor",
                    url="https://www.nber.org/people/hoyt_bleakley",
                    research_areas="economic history, development economics, labor economics, international macroeconomics",
                    keywords=["economic history", "development economics", "labor economics"],
                ),
                faculty(
                    "Dmitriy Stolyarov", title="Professor",
                    url="https://sites.lsa.umich.edu/stolyar/",
                    research_areas="aging and retirement, household finance, financial economics, economic growth, macroeconomics",
                    keywords=["macroeconomics", "household finance", "economic growth"],
                ),
                faculty(
                    "Dean Yang", title="Professor",
                    url="https://deanyang-econ.github.io/deanyang/", email="deanyang@umich.edu",
                    research_areas="development economics, international migration, remittances, international finance",
                    keywords=["development economics", "migration", "international finance"],
                ),
                faculty(
                    "Christopher L. House", title="Professor",
                    url="https://public.websites.umich.edu/~chouse/", email="chouse@umich.edu",
                    research_areas="macroeconomics, monetary business-cycle models, investment dynamics, durable goods, tax policy",
                    keywords=["macroeconomics", "business cycles", "tax policy"],
                ),
            ],
        },
        {
            "short": "PSYCH",
            "name": "Department of Psychology",
            "majors": ["Psychology", "Cognitive Science", "Neuroscience"],
            "directory_url": "https://lsa.umich.edu/psych/people/faculty.html",
            "scrape": _scrape("https://lsa.umich.edu/psych/people/faculty.html", _LSA_SELECTORS, paginate=_LSA_PAGINATE),
            "faculty": [
                faculty(
                    "Ethan Kross", title="Professor",
                    url="https://www.ethankross.com/", email="ekross@umich.edu",
                    research_areas="emotion regulation, self-control, the inner voice, social media and well-being, affective neuroscience",
                    keywords=["emotion regulation", "self-control", "affective neuroscience", "well-being"],
                ),
                faculty(
                    "Susan Gelman", title="Professor",
                    url="https://sites.lsa.umich.edu/gelman-lab/", email="gelman@umich.edu",
                    research_areas="cognitive development, concept and category development, language acquisition, inductive reasoning, essentialism",
                    keywords=["cognitive development", "concepts", "language acquisition", "reasoning"],
                ),
                faculty(
                    "Patricia A. Reuter-Lorenz", title="Professor",
                    url="https://lsa.umich.edu/psych/people/faculty/parl.html", email="parl@umich.edu",
                    research_areas="cognitive aging, working memory, attention, executive control, cognitive neuroscience and neuroimaging",
                    keywords=["cognitive aging", "memory", "cognitive neuroscience", "attention"],
                ),
                faculty(
                    "Richard Gonzalez", title="Professor",
                    url="https://faculty.isr.umich.edu/gonzo/", email="gonzo@umich.edu",
                    research_areas="judgment and decision making, quantitative modeling, risk and uncertainty, medical decision making, product design",
                    keywords=["decision making", "quantitative psychology", "risk", "judgment"],
                ),
                faculty(
                    "Shinobu Kitayama", title="Professor",
                    url="http://kitayama.socialpsychology.org/", email="kitayama@umich.edu",
                    research_areas="cultural psychology, self and identity, cultural neuroscience, emotion and motivation across cultures, self-construal",
                    keywords=["cultural psychology", "social psychology", "cultural neuroscience", "self and identity"],
                ),
                faculty(
                    "Felix Warneken", title="Professor",
                    url="https://sites.lsa.umich.edu/warneken/", email="warneken@umich.edu",
                    research_areas="origins of cooperation, development of altruism, fairness and morality in children, comparative cognition, social cognition development",
                    keywords=["developmental psychology", "cooperation", "social cognition", "comparative cognition"],
                ),
                faculty(
                    "David Dunning", title="Professor",
                    url="https://sites.lsa.umich.edu/dunning-lab/", email="ddunning@umich.edu",
                    research_areas="self-assessment and metacognition, social judgment, motivated reasoning, trust, accuracy of self-perception",
                    keywords=["social psychology", "metacognition", "judgment", "motivated reasoning"],
                ),
            ],
        },
        {
            "short": "AERO",
            "name": "Aerospace Engineering",
            "majors": ["Aerospace Engineering"],
            "directory_url": "https://aero.engin.umich.edu/people/faculty/",
            "faculty": [
                faculty(
                    "Joaquim R. R. A. Martins", title="Professor",
                    url="https://mdolab.engin.umich.edu/staff_members/jmartins",
                    research_areas="multidisciplinary design optimization, aircraft aerodynamic design, aerostructural optimization, adjoint sensitivity methods, computational aircraft design",
                    keywords=["design optimization", "aerodynamics", "computational design", "aircraft design"],
                ),
                faculty(
                    "Krzysztof Fidkowski", title="Professor",
                    url="https://cfdg.engin.umich.edu/people/krzysztof-fidkowski", email="kfid@umich.edu",
                    research_areas="computational fluid dynamics, adjoint-based error estimation, output-based mesh adaptation, high-order discretization, uncertainty quantification",
                    keywords=["computational fluid dynamics", "numerical methods", "mesh adaptation", "uncertainty quantification"],
                ),
                faculty(
                    "Karthik Duraisamy", title="Professor",
                    url="https://aero.engin.umich.edu/people/duraisamy-karthik/", email="kdur@umich.edu",
                    research_areas="scientific machine learning, data-driven turbulence modeling, computational science and engineering, reduced-order modeling, uncertainty quantification",
                    keywords=["scientific machine learning", "turbulence modeling", "reduced-order modeling", "computational science"],
                ),
                faculty(
                    "Benjamin Jorns", title="Associate Professor",
                    url="https://pepl.engin.umich.edu/personnel/professor-benjamin-a-jorns/", email="jorns@umich.edu",
                    research_areas="electric propulsion, Hall thrusters, low-temperature plasma physics, plasma diagnostics, in-space propulsion",
                    keywords=["electric propulsion", "plasma physics", "spacecraft propulsion", "plasma diagnostics"],
                ),
                faculty(
                    "Ilya Kolmanovsky", title="Professor",
                    url="https://aero.engin.umich.edu/people/kolmanovsky-ilya/", email="ilya@umich.edu",
                    research_areas="constrained control systems, model predictive control, spacecraft orbital and attitude control, aerospace control, reference governors",
                    keywords=["control systems", "model predictive control", "spacecraft control", "optimization"],
                ),
                faculty(
                    "Carlos E. S. Cesnik", title="Professor",
                    url="https://a2srl.engin.umich.edu/profile/prof-carlos-e-s-cesnik/",
                    research_areas="computational and experimental aeroelasticity, very flexible aircraft dynamics, hypersonic aerothermoelasticity, structural health monitoring, smart structures",
                    keywords=["aeroelasticity", "structural dynamics", "structural health monitoring", "smart structures"],
                ),
                faculty(
                    "Venkat Raman", title="Professor",
                    url="https://aero.engin.umich.edu/people/raman-venkat/", email="ramanvr@umich.edu",
                    research_areas="turbulent reacting flow simulation, combustion modeling, rotating detonation engines, scramjet and hypersonic propulsion, gas turbine modeling",
                    keywords=["combustion", "computational fluid dynamics", "propulsion", "turbulence"],
                ),
                faculty(
                    "Dennis Bernstein", title="Professor",
                    url="https://aero.engin.umich.edu/people/bernstein-dennis/", email="dsbaero@umich.edu",
                    research_areas="autonomous systems, control systems, sustainable aviation, resilient autonomy",
                    keywords=["autonomous systems", "control systems", "sustainable aviation", "resilient autonomy"],
                ),
                faculty(
                    "Gökçin Çınar", title="Assistant Professor",
                    url="https://aero.engin.umich.edu/people/cinar-gokcin/", email="cinar@umich.edu",
                    research_areas="advanced air mobility, computational engineering, digital engineering, sustainable aviation",
                    keywords=["advanced air mobility", "computational engineering", "digital engineering", "sustainable aviation"],
                ),
                faculty(
                    "James W. Cutler", title="Professor",
                    url="https://aero.engin.umich.edu/people/cutler-james-w/", email="jwcutler@umich.edu",
                    research_areas="autonomous systems, control systems, commercial space, space systems",
                    keywords=["autonomous systems", "control systems", "commercial space", "space systems"],
                ),
                faculty(
                    "Giusy Falcone", title="Assistant Professor",
                    url="https://aero.engin.umich.edu/people/falcone-giusy/", email="falconeg@umich.edu",
                    research_areas="autonomous systems, control systems, commercial space, resilient autonomy",
                    keywords=["autonomous systems", "control systems", "commercial space", "resilient autonomy"],
                ),
                faculty(
                    "Mirko Gamba", title="Professor",
                    url="https://aero.engin.umich.edu/people/gamba-mirko/", email="mirkog@umich.edu",
                    research_areas="aerodynamics, propulsion, commercial space, sustainable aviation",
                    keywords=["aerodynamics", "propulsion", "commercial space", "sustainable aviation"],
                ),
                faculty(
                    "Alex Gorodetsky", title="Associate Professor",
                    url="https://aero.engin.umich.edu/people/gorodetsky-alex/", email="goroda@umich.edu",
                    research_areas="autonomous systems, control systems, computational engineering, digital engineering",
                    keywords=["autonomous systems", "control systems", "computational engineering", "digital engineering"],
                ),
                faculty(
                    "Nakhiah Goulbourne", title="Associate Professor",
                    url="https://aero.engin.umich.edu/people/goulbourne-nakhiah/", email="ngbourne@umich.edu",
                    research_areas="aerospace structures, materials",
                    keywords=["aerospace structures", "materials"],
                ),
                faculty(
                    "George F. Halow", title="Professor",
                    url="https://aero.engin.umich.edu/people/halow-george-f/", email="gfhalow@umich.edu",
                    research_areas="digital engineering, sustainable aviation",
                    keywords=["digital engineering", "sustainable aviation"],
                ),
                faculty(
                    "Daniel J. Inman", title="Professor",
                    url="https://aero.engin.umich.edu/people/inman-daniel-j/", email="daninman@umich.edu",
                    research_areas="advanced air mobility, aerospace structures, materials",
                    keywords=["advanced air mobility", "aerospace structures", "materials"],
                ),
                faculty(
                    "Jean-Baptiste Jeannin", title="Associate Professor",
                    url="https://aero.engin.umich.edu/people/jeannin-jean-baptiste/", email="jeannin@umich.edu",
                    research_areas="autonomous systems, control systems, computational engineering",
                    keywords=["autonomous systems", "control systems", "computational engineering"],
                ),
                faculty(
                    "Oliver Jia-Richards", title="Assistant Professor",
                    url="https://aero.engin.umich.edu/people/jia-richards-oliver/", email="oliverjr@umich.edu",
                    research_areas="aerodynamics, propulsion, autonomous systems, control systems",
                    keywords=["aerodynamics", "propulsion", "autonomous systems", "control systems"],
                ),
                faculty(
                    "Aaron W. Johnson", title="Assistant Professor",
                    url="https://aero.engin.umich.edu/people/johnson-aaron-w/", email="aaronwj@umich.edu",
                    research_areas="commercial space, space systems",
                    keywords=["commercial space", "space systems"],
                ),
            ],
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
