"""Carry dated medical-school appointment evidence across static-seed fallbacks."""


def _set_title(row, title):
    metadata = row["metadata"]
    old = f'Faculty research profile for {metadata["faculty_title"]} {row["pi_name"]}'
    new = f'Faculty research profile for {title + " " if title else ""}{row["pi_name"]}'
    for key in ("description", "description_clean"):
        if isinstance(row.get(key), str):
            row[key] = row[key].replace(old, new, 1)
    metadata["faculty_title"] = title
    if not title and isinstance(row.get("title"), str):
        row["title"] = row["title"].removeprefix("Prof. ")


def withhold_changed_appointment(row):
    _set_title(row, "")
    row["metadata"]["faculty_title_read_status"] = "department_card_changed"


def apply_observation(row, receipt, seen):
    _set_title(row, receipt["title"])
    metadata = row["metadata"]
    metadata.pop("faculty_title_read_status", None)
    row.update(url=receipt["profile"], source_url=receipt["profile"])
    # The directory establishes the listing and quoted position. The remaining
    # medical-school seed fields still have no new individual-page verification.
    metadata.update(faculty_title_observation=receipt.copy(),
                    verification_scope="curated", listing_seen_on_source=True,
                    last_seen_at=seen, last_verified=None)


def preserve_observation(previous, incoming, *, seed_row, roster, profile, department):
    """A file-only fallback must keep the dated department evidence on this person."""
    if not seed_row(incoming) or previous.get("pi_name") != incoming.get("pi_name"):
        return
    if incoming["metadata"].get("faculty_title_read_status") == "department_card_changed":
        return
    metadata = previous.get("metadata") or {}
    if seed_row(previous) and metadata.get("faculty_title_read_status") == "department_card_changed":
        withhold_changed_appointment(incoming)
        return
    receipt = metadata.get("faculty_title_observation") or {}
    if (previous.get("department") == department and previous.get("url") == profile
            and previous.get("source_url") in (profile, roster) and receipt.get("source") == roster
            and receipt.get("profile") == profile and receipt.get("name") == incoming["pi_name"]
            and receipt.get("title") == metadata.get("faculty_title") and metadata.get("last_seen_at")
            and incoming["metadata"].get("verification_scope") == "curated"
            and not incoming["metadata"].get("listing_seen_on_source")):
        apply_observation(incoming, receipt, metadata["last_seen_at"])
