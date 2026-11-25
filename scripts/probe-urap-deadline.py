from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

for url in ('https://urapprojects.berkeley.edu/detail.php?id=20152-2', 'https://urapprojects.berkeley.edu/list.php?status=Open'):
    with urlopen(Request(url, headers={'User-Agent': 'OpportunityFilterEngine source verification'}), timeout=30) as response:
        soup = BeautifulSoup(response.read(), 'html.parser')
        print(response.status, response.geturl())
    for s in soup.find_all(string=True):
        if any(word in str(s).lower() for word in ('fall 2026', 'deadline to apply', 'apprentices needed')):
            print(str(s.parent)[:1100], 'parent class', s.parent.parent.name, s.parent.parent.attrs)
