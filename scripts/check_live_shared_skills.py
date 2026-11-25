from verify_match_reasons import card_pages, profile
p=profile('uiuc','University of Illinois Urbana-Champaign','Computer Science',('machine learning','computer vision'))
def collect(skills,ids=()):
 p['hard_skills']=skills
 rows=card_pages(p,sample_ids=ids)
 return {r['opportunity_id']:(r['final_score'],r['readiness_score'],r.get('gaps')) for r in rows}
normal=collect([{'name':'PyTorch','level':'beginner','source':'typed'}]);ids=list(normal)
assert ids
inherited=collect([{'name':'PyTorch','level':'beginner','source':'shared'}],ids)
empty=collect([],ids)
common=normal.keys() & inherited.keys() & empty.keys()
diff=[key for key in common if inherited[key]!=empty[key]]
mismatch=[key for key in common if inherited[key]!=normal[key]]
print('returned',len(normal),len(inherited),len(empty),'shared_vs_typed_mismatches',len(mismatch),'shared_vs_empty_changes',len(diff),'sample',sorted(diff)[:3],flush=True)

assert len(common)==len(normal)==len(inherited)==len(empty) and not mismatch and diff
