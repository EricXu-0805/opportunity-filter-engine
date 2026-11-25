"""Compare static and currently observed Wesleyan identities in a single no-write collection."""
from src.collectors.schools import wesleyan_faculty

static = wesleyan_faculty.fetch_and_normalize(deep=False)
ledger = {}
rows = wesleyan_faculty.fetch_and_normalize(unit_ledger=ledger)
ids_preserved = {r["id"] for r in rows} == {r["id"] for r in static}
sightings = sum(r["metadata"].get("listing_seen_on_source") is True for r in rows)
unseen = sum(not r["metadata"].get("last_seen_at") for r in rows)
field_dates = sum(bool(r["metadata"].get("last_verified")) for r in rows)
print("Wesleyan candidate", {"rows":len(rows), "static_rows":len(static), "ids_preserved":ids_preserved,
                             "confirmed_listings":sightings,"unobserved":unseen,"field_dates":field_dates,
                             "ledger_units":len(ledger)},flush=True)
assert ids_preserved and len(static) == len(rows) and sightings > 0 and sightings + unseen == len(rows) and field_dates == 0
