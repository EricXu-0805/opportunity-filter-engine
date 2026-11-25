"""Compare long-phrase and single-interest reasons on the 23 original public Berkeley records."""
from verify_match_reasons import profile, request, selected, SENTENCE

IDS = ["faculty-ucb-neuro-36c1f1bc","faculty-ucb-psych-adf7bfeb","faculty-ucb-bioe-9f9e8431","faculty-ucb-eecs-553baf90","faculty-ucb-mcb-2124be94","faculty-ucb-mcb-49fe5366","faculty-ucb-mcb-e4cf2df2","faculty-ucb-eecs-cd584e25","faculty-ucb-eecs-42a31b9f","faculty-ucb-eecs-c7574d80","faculty-ucb-eecs-d05b887d","faculty-ucb-eecs-b9dd9ce9","faculty-ucb-eecs-bdd7d99c","faculty-ucb-eecs-347d29e2","faculty-ucb-eecs-c8da212c","faculty-ucb-eecs-a6bc57e0","faculty-ucb-eecs-bc69e20c","faculty-ucb-eecs-155bfe17","faculty-ucb-eecs-ee03e4f0","faculty-ucb-eecs-0f311e1b","faculty-ucb-mcb-ad393b0d","faculty-ucb-music-35523648","faculty-ucb-tdps-dd42e8c5"]
print("release",request("/health").get("release_sha"),flush=True)
for phrase in (SENTENCE,"memory"):
    cases = selected(profile("ucb","UC Berkeley","Cognitive Science",(phrase,)), IDS)
    attributed = {rid: [reason for reason in row["reasons_fit"] if reason.startswith(("Your interest in memory closely matches","Your interest in circuits closely matches"))] for rid, row in cases.items()}
    hits = [rid for rid, reasons in attributed.items() if reasons]
    print("M188", "long" if phrase == SENTENCE else "short", "checked",len(cases),"of",len(IDS),"single-word attributions",len(hits),"examples",hits[:4],flush=True)
    if not cases:
        raise RuntimeError("no original sample surfaced")
    if phrase == SENTENCE and hits:
        print("REGRESSION remains in this deployed build", flush=True)
    if phrase == "memory" and not hits:
        print("Positive control not established in current target set", flush=True)

