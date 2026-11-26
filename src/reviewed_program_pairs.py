"""Cross-source records whose host, URLs and application cohort have been checked."""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace

from src.program_windows import NCSA_DIRECTORY, WINDOWS, WISCONSIN_DIRECTORY, ProgramWindow, reviewed_window


@dataclass(frozen=True)
class ProgramPair:
    host_id: str
    host_source: str
    window: ProgramWindow
    directory_id: str
    directory_url: str
    previous_directory_ids: tuple[str, ...] = ()

    @property
    def ids(self) -> tuple[str, str]:
        return self.host_id, self.directory_id

    @property
    def historical_ids(self) -> tuple[str, ...]:
        return (*self.ids, *self.previous_directory_ids)

    def verified(self, records: Mapping[str, dict | None], projected: bool = False) -> bool:
        for oid, source, url in (
            (self.host_id, self.host_source, self.window.url),
            (self.directory_id, "uiuc_sro", self.directory_url),
        ):
            record = records.get(oid)
            if not record or record.get("id") != oid or record.get("source") != source or record.get("url") != url:
                return False
            if (record.get("metadata") or {}).get("is_active") is False:
                return False
            if record.get("deadline") != self.window.closes_on.isoformat():
                return False
            checked = reviewed_window(record)
            if checked and checked.page == self.window.page and checked.closes_on == self.window.closes_on:
                continue
            # Public cards omit collector metadata but carry the source-bound opening.
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
        if self.directory_id in existing and self.host_id not in existing:
            return self.directory_id
        return self.host_id

    def redundant_id(self, existing: Collection[str]) -> str:
        return self.directory_id if self.preferred_id(existing) == self.host_id else self.host_id

    def reconcile_pending(self, ids: list[str], source: str) -> list[str]:
        if source:
            wanted = {self.host_source: self.host_id, "uiuc_sro": self.directory_id}.get(source)
            return [oid for oid in ids if oid not in self.ids or oid == wanted]
        if self.host_id in ids and self.directory_id in ids:
            return [oid for oid in ids if oid != self.directory_id]
        return ids


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
SOURCES_BY_PROGRAM = ((NCSA,), (WISCONSIN, _WISCONSIN_FALLBACK))
ALL_IDS = frozenset(oid for choices in SOURCES_BY_PROGRAM for pair in choices for oid in pair.ids)


def verified_pairs(by_id: Mapping[str, dict | None], *, projected: bool = False) -> tuple[ProgramPair, ...]:
    result = []
    for choices in SOURCES_BY_PROGRAM:
        for pair in choices:
            if pair.verified(by_id, projected):
                result.append(pair)
                break
    return tuple(result)


def pairs_in_records(records: Iterable[dict]) -> tuple[ProgramPair, ...]:
    return verified_pairs({r["id"]: r for r in records if r.get("id") in ALL_IDS})
