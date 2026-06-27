"""University of Michigan curated faculty config (via the faculty_graph engine).

Michigan's department directories are Cloudflare-protected (403 to a stdlib
scraper), so this is a hand-verified seed set rather than a live scrape: real
current professors with their research areas and (where reliably confirmable)
public umich.edu emails. Emails left as None where the uniqname could not be
confirmed — never guessed.

Six departments, ~47 professors. One source ("umich_faculty") across all of
them (the UIUC model); the department rides on each record's `department`
field, and ids are namespaced by department short-code so they never collide.

Data verified Jun 2026 from lab/personal sites, Google Scholar, dblp, and
department news (the directory pages themselves block scrapers). Two distinct
professors named "Wei Lu" (ECE/memristors vs ME/batteries) are intentionally
kept separate — the engine de-dups on email/URL, not name.
"""

from __future__ import annotations

from .. import faculty_graph
from ..faculty_graph import faculty

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
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
