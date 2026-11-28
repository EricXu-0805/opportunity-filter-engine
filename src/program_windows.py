"""Application windows read on each configured program's own pages.

A window belongs to one campus program spec (its school, collector key and
row URL) and holds only what the cited page states, in its words. A page that
refused us (HTTP 403, a bot check) gets no window: Johns Hopkins' academic-year
PURA page did on 2026-11-05.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ProgramWindow:
    url: str
    page: str
    reviewed_on: date
    closes_on: date
    closes_quote: str
    opens_on: date | None = None
    opens_quote: str = ""
    zone: str = ""
    opens_text: str = ""  # the opening date as the page writes it

    @property
    def opens_at(self) -> datetime | None:
        """When the stated opening day begins on the campus, or None."""
        if self.opens_on is None:
            return None
        return datetime.combine(self.opens_on, time.min, ZoneInfo(self.zone)).astimezone(UTC)


_REVIEWED = date(2026, 11, 5)
_DSI_HOST = "https://datascience.uchicago.edu/education/summerlab/"
DSI_IDS = ("uchicago-8cd2def060b6", "sro-d6b78515")
DSI_WINDOW = ProgramWindow(
    _DSI_HOST, _DSI_HOST + "program-details/", date(2026, 11, 26), date(2027, 1, 11),
    "Application deadline: January 11, 2027, 11:59pm CT",
)
DSI_WORK_AUTHORIZATION = "All participants need U.S. work authorization and documentation for their stipend."
DSI_CLASS_YEARS = ("freshman", "sophomore", "junior")  # The host FAQ excludes graduating college seniors.
DSI_SUPPORT = (
    "$5,600 for eight weeks in 2027. Optional housing is free for college students. "
    "Selected NSF-funded undergraduates who are U.S. citizens or permanent residents "
    "receive an additional $1,800 for travel and food."
)
_DSI_CLOSES_AT = datetime.combine(DSI_WINDOW.closes_on, time(23, 59), ZoneInfo("America/Chicago"))
_DSI_2027_NOTES = (
    "Applications close January 11, 2027 at 11:59 p.m. Central.",
    "The 2026 program has concluded; the 2027 program application is not posted yet "
    "(the page says to check back in fall 2026). Graduating college seniors are not eligible.",
)
DSI_DIRECTORY = "https://researchops.web.illinois.edu/opportunity/data-science-institute-summer-lab"
_NCSA = "https://reu.ncsa.illinois.edu/"
_SUPERB = "https://eecs.berkeley.edu/resources/undergrads/undergraduate-research/superb/"
_SULI = "https://science.osti.gov/wdts/suli/How-to-Apply"
_HAAS = "https://research.berkeley.edu/haas-scholars/"
_SROP = "https://www.tgs.northwestern.edu/success/thoughtful-recruitment/summer-research-opportunity-program/"
_SFP = "https://sfp.caltech.edu/undergraduate-research/programs/"
_DUKE_FOCUS_DATES = "The form opens on April 1, 2026, and must be submitted by May 13, 2026."
_WISCONSIN_OLD_HOST = "https://wiscience.wisc.edu/IBS-SRP"
_WISCONSIN_HOST = "https://wiscience.wisc.edu/research/summer_research_program/"
_WISCONSIN_WINDOW = ProgramWindow(
    _WISCONSIN_OLD_HOST, _WISCONSIN_HOST, date(2026, 11, 26), date(2027, 2, 10),
    "Apply by February 10, 2027.", date(2026, 11, 1),
    "Open November 1, 2026–February 10, 2027.", "America/Chicago", "November 1, 2026",
)
STARS_HOST = "https://www.bumc.bu.edu/gms/students/summer-training-as-research-scholars-program/"
STARS_OLD_HOST = "https://www.bumc.bu.edu/gms/students/dei/undergraduate-summer-and-youth-programs/stars/"
STARS_WINDOW = ProgramWindow(
    STARS_HOST, STARS_HOST, date(2026, 11, 26), date(2027, 1, 15),
    "application due date January 15th, 2027 at 11:59pm",
)
_SSRP = "https://biosciences.stanford.edu/pathways/ssrp-amgen-scholars-program/"
_SSRP_WINDOW = ProgramWindow(
    _SSRP, _SSRP + "the-ssrp-amgen-scholars-program-application/",
    date(2026, 11, 26), date(2027, 2, 1), "Application Deadline: February 1, 2027 at 11:59 PM PDT",
    date(2026, 11, 1), "Application Open Date: November 1, 2026", "America/Los_Angeles", "November 1, 2026",
)
_MCNAIR_APPLICATION = "https://ucsd-research.academicworks.com/opportunities/2368"
_DART = "https://mga1.wlu.edu/campusnotices/view/web.php?id=9865&view=web"
_GRG = "https://undergradresearch.northwestern.edu/funding/grg/"

# A page that writes its dates without a year ("March 1: Application
# deadline.") names the cycle elsewhere on the same page ("View the 2027
# program flyer!", "SURF 2027 application portal"); that is the year here.
WINDOWS: dict[tuple[str, str], ProgramWindow] = {
    ("bu", "stars"): STARS_WINDOW,
    ("stanford", "ssrp_amgen_scholars"): _SSRP_WINDOW,
    ("ucsd", "mcnair"): ProgramWindow(
        _MCNAIR_APPLICATION, _MCNAIR_APPLICATION, date(2026, 11, 26), date(2026, 11, 20), "Deadline: 11/20/2026",
    ),
    ("duke", "focus_program"): ProgramWindow(
        "https://focus.duke.edu/", "https://focus.duke.edu/for-students/prospective-students/entryprocess",
        date(2026, 11, 26), date(2026, 5, 13), _DUKE_FOCUS_DATES,
        date(2026, 4, 1), _DUKE_FOCUS_DATES,
        "America/New_York", "April 1, 2026",
    ),
    ("manual", "ext-uiuc-ncsa-reu"): ProgramWindow(
        _NCSA, _NCSA, date(2026, 11, 26), date(2027, 2, 15),
        "Online application: December 15, 2026 – February 15, 2027",
        date(2026, 12, 15), "Online application: December 15, 2026 – February 15, 2027",
        "America/Chicago", "December 15, 2026",
    ),
    ("ucb", "eecs_sure"): ProgramWindow(
        _SUPERB, _SUPERB, date(2026, 11, 25), date(2025, 1, 25),
        "Application deadline: January 25th 2025, 11:59 PM ET",
    ),
    ("ucb", "lbl_suli"): ProgramWindow(
        _SULI, _SULI, date(2026, 11, 25), date(2027, 1, 6),
        "Applications are due January 6, 2027 at 5:00 PM ET.",
    ),
    ("ucb", "haas_scholars"): ProgramWindow(
        _HAAS, _HAAS + "how-to-apply/", date(2026, 11, 25), date(2026, 3, 13),
        "Application deadline: Friday, March 13, 2026 at 12:00 PM Noon Pacific Time.",
    ),
    ("northwestern", "nu_tgs_srop"): ProgramWindow(
        _SROP, _SROP + "srop-faq.html", _REVIEWED, date(2027, 2, 10),
        "The official BTAA application opens November 1, 2026 and closes Tuesday, February 10, 2027.",
        date(2026, 11, 1),
        "The official BTAA application opens November 1, 2026 and closes Tuesday, February 10, 2027.",
        "America/Chicago", "November 1, 2026",
    ),
    ("northwestern", "nu_circumnavigator_grant"): ProgramWindow(
        _GRG, _GRG, date(2026, 11, 16), date(2026, 11, 19),
        "DEADLINE Thursday, November 19, 2026 (11:59 PM CST)",
    ),
    ("unl", "unl_summer_research_program"): ProgramWindow(
        "https://summerprogram.unl.edu/", "https://summerprogram.unl.edu/", _REVIEWED, date(2027, 3, 1),
        "March 1: Application deadline.",
        date(2026, 11, 15), "November 15: Online application opens.", "America/Chicago", "November 15",
    ),
    ("uchicago", "dsi_summer_lab"): DSI_WINDOW,
    ("jhu", "summer_pura"): ProgramWindow(
        "https://hour.jhu.edu/opportunities/summerpura/", "https://hour.jhu.edu/opportunities/summerpura/",
        _REVIEWED, date(2027, 2, 1),
        "The Summer PURA program is accepting applications for summer 2027 projects starting 11/1/2026 "
        "through 2/1/2027.",
        date(2026, 11, 1),
        "The Summer PURA program is accepting applications for summer 2027 projects starting 11/1/2026 "
        "through 2/1/2027.",
        "America/New_York", "11/1/2026",
    ),
    ("caltech", "surf"): ProgramWindow(
        _SFP + "surf", _SFP + "surf/application_information", _REVIEWED, date(2027, 2, 22),
        "SURF applications are due on February 22.",
    ),
    ("caltech", "surf_jpl"): ProgramWindow(
        _SFP + "surfjpl", _SFP + "surfjpl/application-information", _REVIEWED, date(2027, 2, 22),
        "SURF@JPL applications are due on February 22.",
    ),
    ("caltech", "wave_fellows"): ProgramWindow(
        _SFP + "wavefellows", _SFP + "wavefellows/application_information", _REVIEWED, date(2027, 1, 8),
        "Applications are due on or before January 8.",
    ),
    ("wisc", "ibs_srp_cmbs_reu"): _WISCONSIN_WINDOW,
    ("wlu", "wlu_dart"): ProgramWindow(
        _DART, _DART, date(2026, 11, 26), date(2026, 2, 8),
        "via email by February 8th",
    ),
}


# Aggregator IDs can outlive the cohort their source pages described. Keep the
# exact incoming estimate with the host window so it cannot migrate to another
# year, a replaced program, or a newly confirmed date.
NCSA_DIRECTORY = (
    "https://researchops.web.illinois.edu/opportunity/"
    "future-discovery-training-students-build-and-apply-open-source-machine-learning-models"
)
WISCONSIN_DIRECTORY = "https://researchops.web.illinois.edu/opportunity/cellular-and-molecular-biology-stress-summer-research-program"
_UND_AWARD = "https://www.nsf.gov/awardsearch/showAward?AWD_ID=2447669"
_CRISP_DIRECTORY = "https://researchops.web.illinois.edu/opportunity/cancer-research-internship-summer-program-crisp"
_CRISP_HOST = "https://cancer.iu.edu/education/summer/acs-cancer-research-internship.html"
_CRISP_DATES = "Applications open Nov. 15, 2026 and close Jan. 31, 2027."
SMU_DIRECTORY = "https://researchops.web.illinois.edu/opportunity/reu-advancing-data-science-public-interest"
_SMU_PROGRAM = (
    "https://www.smu.edu/Provost/saes/academic-enrichment/engaged-learning/"
    "research/research-experiences-undergraduates/data-science-reu"
)
_SMU_DATES = "11/19/2026 - 02/22/2027 11:59 PM ET"
SMU_WINDOW = ProgramWindow(
    "https://www.nsf.gov/awardsearch/showAward?AWD_ID=2447670",
    "https://etap.nsf.gov/award/8314/opportunity/12305",
    date(2026, 11, 26), date(2027, 2, 22), _SMU_DATES,
    date(2026, 11, 19), _SMU_DATES, "America/New_York", "11/19/2026",
)
STARS_SRO_IDS = ("sro-60f60fbd", "sro-bc33bc08")
_STARS_SRO = "https://researchops.web.illinois.edu/opportunity/summer-training-research-scholars"
STARS_SRO_CURRENT = _STARS_SRO + "-stars-program"
STARS_SRO_ALIAS = _STARS_SRO + "-program-stars"
_SRO = "https://researchops.web.illinois.edu/opportunity/"
_MICHHERS_DIRECTORY = _SRO + "michigan-humanities-emerging-research-scholars-program-michhers"
_MICHHERS = "https://rackham.umich.edu/prospective-students/michhers/"
_MICROSURP_DIRECTORY = _SRO + "microbiology-summer-undergraduate-research-program-microsurp-trainee-program"
_MICROSURP = "https://med.uth.edu/mmg/summer-research-program/"
SRO_WINDOW_ORGANIZATIONS = {
    "sro-d6b78515": "University of Chicago",
    **dict.fromkeys(STARS_SRO_IDS, "Boston University"),
    "sro-e74d89e9": "University of Michigan",
    "sro-7f860ddc": "McGovern Medical School",
    "sro-595e912d": "University of Wisconsin-Madison",
    "sro-3c378261": "University of Wisconsin-Madison",
}
_AGGREGATOR_WINDOWS = {
    ("uiuc_sro", "sro-d6b78515"): ("2027-01-12", replace(DSI_WINDOW, url=DSI_DIRECTORY)),
    ("uiuc_sro", "sro-e74d89e9"): ("2027-02-10", ProgramWindow(
        _MICHHERS_DIRECTORY, _MICHHERS, date(2026, 11, 26), date(2027, 2, 1),
        "Application Close: Monday, February 1, 2027", date(2026, 12, 2),
        "Application Open: Wednesday, December 2, 2026", "America/Detroit", "December 2, 2026",
    )),
    ("uiuc_sro", "sro-7f860ddc"): ("2027-02-01", ProgramWindow(
        _MICROSURP_DIRECTORY, _MICROSURP, date(2026, 11, 26), date(2027, 2, 1),
        "due by midnight on Monday, February 1, 2027.", date(2026, 12, 1),
        "Application is open on Tuesday, December 1, 2026", "America/Chicago", "December 1, 2026",
    )),
    ("uiuc_sro", "sro-60f60fbd"): ("2027-02-01", replace(STARS_WINDOW, url=STARS_SRO_CURRENT)),
    ("uiuc_sro", "sro-bc33bc08"): ("2027-02-01", replace(STARS_WINDOW, url=STARS_SRO_ALIAS)),
    ("uiuc_sro", "sro-3ec4ea4e"): ("2027-02-01", ProgramWindow(
        _CRISP_DIRECTORY, _CRISP_HOST, date(2026, 11, 26), date(2027, 1, 31), _CRISP_DATES,
        date(2026, 11, 15), _CRISP_DATES, "America/Indiana/Indianapolis", "Nov. 15, 2026",
    )),
    ("uiuc_sro", "sro-44f176cd"): ("2027-02-15", replace(SMU_WINDOW, url=SMU_DIRECTORY)),
    ("nsf_reu", "nsf-reu-2447670"): ("2026-02-15", SMU_WINDOW),
    ("uiuc_sro", "sro-1532726e"): (
        "2027-03-15", replace(WINDOWS[("manual", "ext-uiuc-ncsa-reu")], url=NCSA_DIRECTORY),
    ),
    ("uiuc_sro", "sro-595e912d"): (
        "2027-02-15", replace(_WISCONSIN_WINDOW, url=WISCONSIN_DIRECTORY + "-0"),
    ),
    ("uiuc_sro", "sro-3c378261"): (
        "2027-02-15", replace(_WISCONSIN_WINDOW, url=WISCONSIN_DIRECTORY),
    ),
    ("nsf_reu", "nsf-reu-2447669"): ("2026-02-15", ProgramWindow(
        _UND_AWARD, "https://med.und.edu/education-training/biomedical-sciences/reu/index.html",
        date(2026, 11, 26), date(2026, 3, 15), "Applications will be accepted through March 15, 2026.",
    )),
}


_SRO_APPLICATION_LINKS = {
    DSI_DIRECTORY: {_DSI_HOST, _DSI_HOST + "#program-overview"},
    _MICHHERS_DIRECTORY: {_MICHHERS, "https://rackham.umich.edu/rackham-life/diversity-equity-and-inclusion/michhers/"},
    _MICROSURP_DIRECTORY: {_MICROSURP},
    STARS_SRO_CURRENT: {STARS_HOST},
    STARS_SRO_ALIAS: {STARS_OLD_HOST, STARS_HOST},
    _CRISP_DIRECTORY: {_CRISP_DIRECTORY, _CRISP_HOST},
    SMU_DIRECTORY: {SMU_DIRECTORY, _SMU_PROGRAM, _SMU_PROGRAM.lower()},
    WISCONSIN_DIRECTORY: {WISCONSIN_DIRECTORY, _WISCONSIN_HOST, "https://wiscience.wisc.edu/research/srp/"},
    NCSA_DIRECTORY: {NCSA_DIRECTORY, _NCSA},
    WISCONSIN_DIRECTORY + "-0": {WISCONSIN_DIRECTORY + "-0", _WISCONSIN_HOST, _WISCONSIN_OLD_HOST},
}


def _aggregator_window(record: dict, original_estimate: str, window: ProgramWindow) -> ProgramWindow | None:
    if record.get("url") != window.url:
        return None
    deadline = record.get("deadline")
    if deadline != window.closes_on.isoformat() and not (
        deadline == original_estimate and (
            record.get("deadline_is_estimate") is True
            or (window.url == STARS_SRO_CURRENT and record.get("deadline_is_estimate") is False)
        )
    ):
        return None
    source_url = record.get("source_url")
    if record["source"] == "nsf_reu":
        award_id = str(record["metadata"].get("nsf_award_id"))
        if source_url != window.url or record["id"] != f"nsf-reu-{award_id}":
            return None
        if window is SMU_WINDOW and (
            record.get("lab_or_program") != "Advancing Data Science in the Public Interest"
            or record.get("organization") != "Southern Methodist University"
        ):
            return None
    else:
        # SRO records the pagination URL as source_url. The stable detail URL
        # identifies the entry; the deep page supplies its external host link.
        if not isinstance(source_url, str) or source_url.split("?", 1)[0] != "https://researchops.web.illinois.edu/":
            return None
        organization = SRO_WINDOW_ORGANIZATIONS.get(record["id"])
        observed_organization = record.get("organization")
        if organization and observed_organization != organization:
            # The legacy Wisconsin calendar was also verified by the stable
            # directory permalink before shallow reads included a host name.
            if window.page != _WISCONSIN_HOST or observed_organization:
                return None
        application = record.get("application")
        if not isinstance(application, dict) or application.get("application_url") not in _SRO_APPLICATION_LINKS[window.url]:
            return None
    return window


def reviewed_window(record: object) -> ProgramWindow | None:
    """The window of the configured program ``record`` is, or None.

    None for a discovered page, and for a row whose URL is not the one we
    read the window for: a config that moved the program to a new page has
    not had the new page read.
    """
    metadata = record.get("metadata") if isinstance(record, dict) else None
    if not isinstance(metadata, dict) or metadata.get("discovered"):
        return None
    if record.get("source") in ("nsf_reu", "uiuc_sro"):
        identifier = record.get("id")
        if not isinstance(identifier, str):
            return None
        entry = _AGGREGATOR_WINDOWS.get((record["source"], identifier))
        return _aggregator_window(record, *entry) if entry else None
    school, key = metadata.get("collector_school"), metadata.get("collector_key")
    # A manual entry has a stable ID instead of collector coordinates. Its
    # two stored source URLs must still match the reviewed page below.
    if record.get("source") == "manual":
        school, key = "manual", record.get("id")
    # Berkeley's dedicated registry encodes its owner in its emitted source.
    # Both the old national row and its campus replacement carry the same key.
    if school is None and record.get("source") in {"ucb_external_research", "ucb_research_programs"}:
        school = "ucb"
    if not isinstance(school, str) or not isinstance(key, str):
        return None
    window = WINDOWS.get((school, key))
    if window is None or record.get("url") != window.url or record.get("source_url") != window.url:
        return None
    if (school, key) == ("ucsd", "mcnair") and (
        record.get("id") != "ucsd-c6d547c9321a" or record.get("source") != "ucsd_research_programs"
        or record.get("deadline") not in (None, window.closes_on.isoformat())
    ):
        return None
    if school == "manual" and record.get("deadline") not in (None, window.closes_on.isoformat()):
        return None
    # The legacy Wisconsin host redirects to a multi-year program. A later
    # campus harvest with a different explicit date describes another cycle.
    if window is DSI_WINDOW and (
        record.get("id") != "uchicago-8cd2def060b6" or record.get("source") != "uchicago_external_research"
        or record.get("deadline") not in (None, window.closes_on.isoformat())
        or metadata.get("deadline_note") not in _DSI_2027_NOTES
    ):
        return None
    if window is _SSRP_WINDOW and (
        record.get("id") != "stanford-1a20b2e045cf" or record.get("source") != "stanford_external_research"
        or record.get("deadline") not in (None, window.closes_on.isoformat())
        or "February 1, 2027" not in str(metadata.get("deadline_note") or "")
    ):
        return None
    if window is STARS_WINDOW and (
        record.get("id") != "bu-bbc659c6ac92" or record.get("source") != "bu_research_programs"
        or record.get("deadline") not in (None, window.closes_on.isoformat())
    ):
        return None
    if window is _WISCONSIN_WINDOW and (
        record.get("id") != "wisc-86cba49b83d7" or record.get("source") != "wisc_external_research"
        or record.get("deadline") not in (None, window.closes_on.isoformat())
    ):
        return None
    return window


def reviewed_program_cutoff(record: dict) -> datetime | None:
    """The host's published instant, only for the two verified 2027 DSI records."""
    if record.get("id") not in DSI_IDS:
        return None
    window = reviewed_window(record)
    if window and window.page == DSI_WINDOW.page and record.get("deadline") == window.closes_on.isoformat():
        return _DSI_CLOSES_AT
    return None


def _apply_dsi_host_terms(record: dict) -> None:
    # The campus seed and previously stored rows can still have the old summary.
    # Preserve any accompanying text captured from the live university page.
    old_end = "Prior research experience is not required."
    restrictions = (
        "College applicants must remain enrolled in fall 2027; high school applicants must live and attend "
        "school in the Chicago area. International undergraduates can apply with documented U.S. work authorization."
    )
    for key in ("description", "description_clean", "description_raw"):
        value = record.get(key)
        if not isinstance(value, str):
            continue
        summary, separator, source_text = value.partition("\n\nFrom the program page: ")
        if summary.endswith(old_end):
            record[key] = f"{summary} {restrictions}{separator}{source_text}"
    if record.get("compensation_details") in (
        "$5,600 stipend for 8 weeks (2026), plus free optional housing",
        "$5,600 stipend for 8 weeks (2027), plus free optional housing",
    ):
        record["compensation_details"] = DSI_SUPPORT


def apply_program_window(record: dict) -> None:
    """Make the window's stated close the row's deadline, in place.

    The deadline is then a stated one (`src.evidence.stated_listing_deadline`):
    the row is offered until it passes and closed after. A row with a stated
    close is not rolling, so "No deadline listed" does not return it.
    """
    window = reviewed_window(record)
    if window is not None:
        if window is DSI_WINDOW:
            _apply_dsi_host_terms(record)
        elif window.page == DSI_WINDOW.page and record.get("compensation_details") == "$5,600":
            record["metadata"]["directory_compensation"] = record["compensation_details"]
            record["compensation_details"] = DSI_SUPPORT
        if window.page == DSI_WINDOW.page:
            if record.get("compensation_details") == DSI_SUPPORT and record.get("paid") in ("yes", "stipend"):
                record["paid"] = "yes"
                stamps = record["metadata"].get("inferred_fields")
                if isinstance(stamps, dict) and stamps.get("paid") == "default:configured_program":
                    stamps.pop("paid")
            eligibility = record.get("eligibility")
            if isinstance(eligibility, dict) and window is not DSI_WINDOW:
                # The directory page states no class year; its collector writes all four on every row.
                eligibility["preferred_year"] = list(DSI_CLASS_YEARS)
                stamps = record["metadata"].get("inferred_fields")
                if isinstance(stamps, dict):
                    stamps.pop("eligibility.preferred_year", None)
            if isinstance(eligibility, dict) and eligibility.get("citizenship_required") is not True:
                original = eligibility.get("work_auth_notes")
                if original in (None, "", "No Citizenship Requirements", DSI_WORK_AUTHORIZATION):
                    if original == "No Citizenship Requirements":
                        record["metadata"]["superseded_work_auth_notes"] = {"value": original, "source_url": record["url"]}
                    eligibility.update(work_auth_notes=DSI_WORK_AUTHORIZATION,
                                       citizenship_required=False, international_friendly="yes")
                    # The data loader stamps campus configuration before applying reviewed host terms.
                    # These two fields now come from the host FAQ, including on a previously stored row.
                    stamps = record["metadata"].get("inferred_fields")
                    if isinstance(stamps, dict):
                        for key in ("eligibility.citizenship_required", "eligibility.international_friendly"):
                            if stamps.get(key) in ("default:configured_program", "rule:sro_page_citizenship_keywords"):
                                stamps.pop(key)
        incoming_date = record.get("deadline")
        incoming_estimate = record.get("deadline_is_estimate")
        record["deadline"] = window.closes_on.isoformat()
        record["deadline_is_estimate"] = False
        record["is_rolling"] = False
        if record.get("source") in ("nsf_reu", "uiuc_sro"):
            metadata = record["metadata"]
            if window is SMU_WINDOW:
                # The grant starts in 2025. ETAP names June 2027 for this cohort,
                # without a day. Keep the award's date out of the program display.
                if record.get("start_date") in ("2025-12-01", "12/01/2025"):
                    metadata["nsf_award_start_date"] = record["start_date"]
                    record["start_date"] = None
                metadata["superseded_award_deadline_estimate"] = {
                    "date": "2026-02-15", "source_url": window.url,
                }
                application = record.get("application")
                if isinstance(application, dict) and application.get("application_url") == window.url:
                    application["application_url"] = window.page
            if record["source"] == "uiuc_sro":
                # The directory may publish an explicit date that differs from the host's.
                if window.page == STARS_HOST:
                    record["application"]["application_url"] = STARS_HOST
                original_estimate, _ = _AGGREGATOR_WINDOWS[(record["source"], record["id"])]
                if incoming_date == original_estimate and (incoming_estimate is True or incoming_date != record["deadline"]):
                    metadata["superseded_directory_deadline"] = {
                        "date": original_estimate,
                        "anticipated": incoming_estimate is True,
                        "source_url": window.url,
                    }
            metadata.pop("deadline_note", None)
            stamps = metadata.get("inferred_fields")
            if isinstance(stamps, dict):
                stamps.pop("deadline", None)


def read_before_opening(record: dict) -> bool:
    """Whether the row's page was last read before its window's stated opening.

    A status read then ("Apply now" left up from the last cycle) cannot say
    this cycle opened. A row with no readable read time counts as read
    before.
    """
    window = reviewed_window(record)
    opens_at = window.opens_at if window is not None else None
    if opens_at is None:
        return False
    try:
        read_at = datetime.fromisoformat(record["metadata"]["last_verified"])
    except (KeyError, TypeError, ValueError):
        return True
    if read_at.tzinfo is None:
        read_at = read_at.replace(tzinfo=UTC)  # the collectors write naive UTC
    return read_at < opens_at


def public_opening(record: dict) -> dict | None:
    """The stated opening a client shows until it passes, or None.

    ``at`` is when the opening day begins on the campus; a client compares it
    with its own clock, so a served payload never goes stale at the boundary.
    """
    window = reviewed_window(record)
    if window is None or window.opens_at is None:
        return None
    return {
        "on": window.opens_on.isoformat(),
        "at": window.opens_at.isoformat(),
        "text": window.opens_text,
        "quote": window.opens_quote,
        "source_url": window.page,
    }
