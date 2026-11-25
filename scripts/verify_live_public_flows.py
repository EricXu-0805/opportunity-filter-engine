"""Read public JoinALab product surfaces using synthetic inputs only."""
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request,urlopen
from bs4 import BeautifulSoup
from urllib.parse import urlencode

base='https://joinalab.com'
scope='mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2'
def get(path,payload=None):
    return json.load(urlopen(Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'}),timeout=45))
def detail(oid):
    return get('/api/opportunities/'+oid+'?'+urlencode({'_release_scope':scope}))
def html(oid):
    return BeautifulSoup(urlopen(base+'/opportunities/'+oid,timeout=40).read(),'html.parser')
def material():
    shared={'name':'PyTorch','level':'beginner','source':'shared'}
    for label,skills,expected in [
        ('shared',[shared],False),('confirmed',[{**shared,'confirmed':True}],True),
        ('with-independent-entry',[shared,{'name':'PyTorch','level':'expert','source':'typed','confirmed':True}],True)]:
        p={'name':'Example Student','year':'sophomore','major':'Engineering','school':'University of Colorado Boulder','hard_skills':skills}
        out=get('/api/cold-email',{'engine':'template','profile':p,'opportunity_id':'boulder-0d8edc5782f3'})
        assert out['method']=='template' and out['body'].strip()
        count=out['body'].lower().count('pytorch')
        assert (count>0)==expected,(label,count)
        print('M213',label,'mentions',count,'version',out.get('email_pipeline_version',out.get('pipeline_version')),flush=True)
def reviewed(item):
    oid,url=item; api=detail(oid); s=html(oid)
    assert api['url']==url and any(a['href']==url for a in s.select('a[href]')) and s.select_one('h1')
    if oid.endswith('5e8e0edd'):assert api['target_truth']['reason_code']=='inactive' and api['metadata']['faculty_title']=='Professor Emerita'
    else:assert api['target_truth']['actionable']
    print('M195',oid,'public detail links to reviewed destination; actionable',api['target_truth']['actionable'],flush=True)
def berkeley():
    oid='ucb-urap-proj-4029d15a89db';d=detail(oid);s=html(oid)
    assert d['target_truth']['reason_code']=='listing_closed' and not d['target_truth']['actionable'] and d['target_truth']['reference_only']
    assert 'steelhead' in s.select_one('h1').get_text(strip=True).lower()
    controls=[a.get_text(' ',strip=True).lower() for a in s.select('a,button')]
    assert 'apply now' not in controls and 'open application page' not in controls and 'closed' in ' '.join(s.stripped_strings).lower()
    print('M211',oid,'closed; reference-only; original study and source visible; application controls',0,flush=True)
def clauses(expected):
    ids=list(expected)
    rows=get('/api/opportunities/batch',{'ids':ids})['opportunities']
    assert {r['id'] for r in rows}==set(ids)
    for r in rows:
        assert not set(expected[r['id']]) & set(r.get('keywords',[]))
    print('M186 original faculty IDs',len(rows),'removed fragments absent',sum(map(len,expected.values())),flush=True)
print('Release',get('/api/health')['release_sha'],flush=True)
material()
with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(reviewed,{'faculty-osu-fabe-1abc04a0': 'https://agsafety.osu.edu/people/dee-jepsen-phd', 'faculty-sbu-cs-7c922688': 'https://researchconnect.stonybrook.edu/en/persons/paola-cascante-bonilla/', 'faculty-sbu-cs-890dcd54': 'https://alps-lab.github.io/', 'faculty-tamu-inta-c32e8252': 'https://bush.tamu.edu/directory/john-schuessler/', 'faculty-umd-math-1516d149': 'https://www-math.umd.edu/signage-directory-faculty/2025-sberhanu.html', 'faculty-umd-phys-5e8e0edd': 'https://umdphysics.umd.edu/directory/faculty/emeritus/beise.html'}.items()))
berkeley()
clauses({'faculty-amherst-math-b56770ee': ['which combines techniques from analysis'], 'faculty-amherst-fren-7b776710': ['which analyzes the relationship between vision'], 'faculty-amherst-thda-511b2f0c': ['which were transmitted through storytelling'], 'faculty-dartmouth-clas-aee33fc6': ['which combines these themes'], 'faculty-dartmouth-engl-43ac6fab': ['which include psychoanalysis'], 'faculty-dartmouth-envs-6c04e1f8': ['which features discussions of the lives'], 'faculty-dartmouth-govt-a845067b': ['which examines the history of CEDAW'], 'faculty-dartmouth-ascl-93db6d36': ['which looks at how individual artists'], 'faculty-dartmouth-lalacs-407368ef': ['which spans film history'], 'faculty-ncsu-mbs-a727f59b': ['which began in 2016'], 'faculty-ncsu-bae-3ead0841': ['which include autonomous navigation'], 'faculty-nd-ceees-064cb01e': ['which recognizes the best design'], 'faculty-nd-phys-ad75cb28': ['takes place in novae and supernovae', 'which'], 'faculty-northwestern-psych-668331e4': ['which can guide their identities'], 'faculty-vanderbilt-math-aca9b9bb': ['which may be quite complicated. But']})


def verify_saved_faculty(old, current):
    archived = detail(old)
    assert archived['id'] == old
    assert archived['metadata']['duplicate_of'] == current
    assert archived['current_faculty_id'] == current
    assert archived['target_truth']['reason_code'] == 'inactive'
    assert not archived['target_truth']['actionable']
    for lang, label in [('en', 'View current faculty record'), ('zh', '查看当前教师档案')]:
        headers = {'Cookie': 'ofe_lang=' + lang}
        old_url = base + '/opportunities/' + old
        with urlopen(Request(old_url, headers=headers), timeout=35) as response:
            page = BeautifulSoup(response.read(), 'html.parser')
        links = [a for a in page.select('a[href]') if a.get_text(strip=True) == label]
        assert len(links) == 1, (old, lang, len(links))
        assert links[0]['href'] == '/opportunities/' + current
        with urlopen(Request(base + links[0]['href'], headers=headers), timeout=35) as response:
            target = BeautifulSoup(response.read(), 'html.parser')
            assert target.select_one('h1') and response.status == 200
        print('PASS saved ID', old, lang, label, current, target.select_one('h1').get_text(strip=True), flush=True)
    destination = detail(current)
    assert destination['id'] == current and destination['target_truth']['actionable']


with ThreadPoolExecutor(max_workers=2) as pool:
    checks = [pool.submit(verify_saved_faculty, old, current) for old, current in [
        ('faculty-georgetown-engl-9b02f5b4', 'faculty-georgetown-engl-be9bd333'),
        ('faculty-purdue-cs-412c3ce0', 'faculty-purdue-cs-bb6831d2'),
    ]]
    for check in checks:
        check.result()
