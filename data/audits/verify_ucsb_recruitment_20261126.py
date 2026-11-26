"""Run the candidate production collector read-only against UCSB's public sources."""
import json
import sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
repo=Path("product").resolve()
sys.path.insert(0,str(repo))
from src.collectors import ucsb_urca_projects as urca
from src.evidence import target_truth

captured_at=datetime.now(timezone.utc).isoformat()
rows,scope=urca.fetch_and_normalize_with_evidence()
assert scope["sitemap_complete"] and scope["directory_rows"]>0 and rows
before=json.loads((repo/"data/processed/shards/ucsb.json").read_text())
existing={r["id"]:r for r in before if r.get("source")==urca.SOURCE}
incoming={r["id"]:r for r in rows}
def posture(row):
    t=target_truth(row)
    return {"actionable":t.actionable,"reason":t.reason_code,"state":t.listing_state,
            "recruiting_directory":row["metadata"].get("urca_directory"),"title":row["title"],"source_url":row["source_url"]}
control_ids=("ucsb-urca-proj-67fca359b647","ucsb-urca-proj-e5cbe0e218a7","ucsb-urca-proj-2eb2c063674e")
cases={oid:posture(incoming[oid]) for oid in control_ids}
assert cases[control_ids[0]]["reason"]=="inactive" and cases[control_ids[1]]["reason"]=="reference_only"
assert cases[control_ids[2]]["actionable"] and cases[control_ids[2]]["state"]=="open"
links_changed=[oid for oid in incoming.keys() & existing.keys() if existing[oid]["source_url"]!=incoming[oid]["source_url"]]
old_active_missing=[oid for oid in existing.keys()-incoming.keys() if existing[oid]["metadata"].get("is_active") is not False]
unexpected=[oid for oid in incoming.keys() & existing.keys() if target_truth(existing[oid]).actionable!=target_truth(incoming[oid]).actionable]
receipt={"observed_utc":captured_at,"completed_utc":datetime.now(timezone.utc).isoformat(),"scope":"read-only product collector, no publication or production mutation",
         "reviewed_commit":"3c3e3cdc1baa8fbf197d963624f87c3b071fff22","sitemap":urca.SITEMAP_INDEX,"directory":urca.PORTAL,
         "source_counts":scope,"live_sitemap_project_ids":len(incoming),"existing_ids":len(existing),"old_active_ids_missing":old_active_missing,
         "changed_source_links":links_changed,"added_project_ids":sorted(incoming.keys()-existing.keys()),"different_actionability_from_committed_shard":unexpected,
         "source_postures":dict(Counter(target_truth(row).reason_code or "actionable" for row in rows)),"control_ids":cases}
out=Path("evidence");out.mkdir(exist_ok=True)
(out/"ucsb-urca-collector.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n")
print(json.dumps(receipt,ensure_ascii=False),flush=True)
assert not old_active_missing and not links_changed and not unexpected
