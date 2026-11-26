"""Cross-source records whose host, URLs and application cohort have been checked."""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace

from src.program_windows import (
    DSI_DIRECTORY,
    DSI_WINDOW,
    NCSA_DIRECTORY,
    SMU_DIRECTORY,
    SMU_WINDOW,
    STARS_SRO_ALIAS,
    STARS_SRO_CURRENT,
    STARS_WINDOW,
    WINDOWS,
    WISCONSIN_DIRECTORY,
    ProgramWindow,
    reviewed_window,
)


@dataclass(frozen=True)
class ProgramPair:
    host_id: str
    host_source: str
    window: ProgramWindow
    directory_id: str
    directory_url: str
    previous_directory_ids: tuple[str, ...] = ()
    additional_directory_ids: tuple[str, ...] = ()

    @property
    def directory_ids(self) -> tuple[str, ...]:
        return self.directory_id, *self.additional_directory_ids

    @property
    def ids(self) -> tuple[str, ...]:
        return self.host_id, *self.directory_ids

    @property
    def historical_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.ids, *self.previous_directory_ids)))

    def verified(self, records: Mapping[str, dict | None], projected: bool = False) -> bool:
        for oid, source, url in (
            (self.host_id, self.host_source, self.window.url),
            (self.directory_id, "uiuc_sro", self.directory_url),
        ):
            record = records.get(oid)
            if not record or record.get("id") != oid or record.get("source") != source or record.get("url") != url:
                return False
            metadata = record.get("metadata")
            if metadata is not None and (not isinstance(metadata, dict) or metadata.get("is_active") is False):
                return False
            if record.get("deadline") != self.window.closes_on.isoformat():
                return False
            checked = reviewed_window(record)
            if checked and checked.page == self.window.page and checked.closes_on == self.window.closes_on:
                continue
            # A verified closing-date citation also identifies programs with no stated opening day.
            if (projected and self.window in (STARS_WINDOW, DSI_WINDOW) and record.get("deadline_is_estimate") is False
                    and record.get("application_deadline_source_url") == self.window.page):
                continue
            # Other public cards omit collector metadata but carry the source-bound opening.
            opening = record.get("application_opens")
            if not (
                projected
                and isinstance(opening, dict)
                and self.window.opens_on
                and opening.get("source_url") == self.window.page
                and opening.get("on") == self.window.opens_on.isoformat()
            ):
                return False
        return True

    def preferred_id(self, existing: Collection[str]) -> str:
        if self.host_id not in existing:
            for oid in self.directory_ids:
                if oid in existing:
                    return oid
        return self.host_id

    def redundant_ids(self, matched: Collection[str], preferred: Collection[str] = ()) -> set[str]:
        if self.host_id not in matched:
            # Source-only views retain every matching directory record. The
            # directory collector owns its own retirement and fallback rules.
            return set()
        members = {oid for oid in self.ids if oid in matched}
        keep = self.preferred_id(members.intersection(preferred))
        return members - {keep}

    def reconcile_pending(self, ids: list[str], source: str) -> list[str]:
        allowed = {self.host_source: (self.host_id,), "uiuc_sro": self.directory_ids, "": self.ids}.get(source, ())
        # A queued reminder retains one of its own links, including when it
        # contains two directory IDs and never contained the campus ID.
        keep = next((oid for oid in allowed if oid in ids), None)
        return [oid for oid in ids if oid not in self.ids or oid == keep]


DSI = ProgramPair(
    "uchicago-8cd2def060b6", "uchicago_external_research", DSI_WINDOW, "sro-d6b78515", DSI_DIRECTORY,
)
NCSA = ProgramPair(
    "ext-uiuc-ncsa-reu", "manual", WINDOWS[("manual", "ext-uiuc-ncsa-reu")], "sro-1532726e", NCSA_DIRECTORY
)
# The SRO collector owns its separate, historically published directory alias.
# Its earlier surviving record and the university host are the cross-source pair.
WISCONSIN = ProgramPair(
    "wisc-86cba49b83d7",
    "wisc_external_research",
    WINDOWS[("wisc", "ibs_srp_cmbs_reu")],
    "sro-595e912d",
    WISCONSIN_DIRECTORY + "-0",
    ("sro-3c378261",),
)
_WISCONSIN_FALLBACK = replace(
    WISCONSIN,
    directory_id="sro-3c378261",
    directory_url=WISCONSIN_DIRECTORY,
    previous_directory_ids=(WISCONSIN.directory_id,),
)
# In the interim both SRO pages can be present. Respect the collector's
# preferred live entry, including the other entry when the original withdraws.
SMU = ProgramPair("nsf-reu-2447670", "nsf_reu", SMU_WINDOW, "sro-44f176cd", SMU_DIRECTORY)
STARS = ProgramPair(
    "bu-bbc659c6ac92", "bu_research_programs", STARS_WINDOW, "sro-60f60fbd", STARS_SRO_CURRENT,
    ("sro-bc33bc08",),
)
_STARS_FALLBACK = replace(
    STARS, directory_id="sro-bc33bc08", directory_url=STARS_SRO_ALIAS, previous_directory_ids=(STARS.directory_id,),
)
SOURCES_BY_PROGRAM = ((DSI,), (NCSA,), (WISCONSIN, _WISCONSIN_FALLBACK), (SMU,), (STARS, _STARS_FALLBACK))
ALL_IDS = frozenset(oid for choices in SOURCES_BY_PROGRAM for pair in choices for oid in pair.ids)


def verified_pairs(by_id: Mapping[str, dict | None], *, projected: bool = False) -> tuple[ProgramPair, ...]:
    result = []
    for choices in SOURCES_BY_PROGRAM:
        for pair in choices:
            if pair.verified(by_id, projected):
                if pair is STARS or pair is _STARS_FALLBACK:
                    other_pair = _STARS_FALLBACK if pair is STARS else STARS
                    if other_pair.verified(by_id, projected):
                        # Both directories still appear before the next SRO
                        # collection. Each has independently passed the host,
                        # destination, activity and cohort checks above.
                        pair = replace(pair, additional_directory_ids=(other_pair.directory_id,))
                    else:
                        other = by_id.get(other_pair.directory_id)
                        metadata = other.get("metadata") if other else None
                        if other and (not isinstance(metadata, dict) or metadata.get("is_active") is not False):
                            # The live ID now describes a different program or cycle.
                            pair = replace(pair, previous_directory_ids=())
                result.append(pair)
                break
    return tuple(result)


def pairs_in_records(records: Iterable[dict]) -> tuple[ProgramPair, ...]:
    return verified_pairs({r["id"]: r for r in records if r.get("id") in ALL_IDS})
