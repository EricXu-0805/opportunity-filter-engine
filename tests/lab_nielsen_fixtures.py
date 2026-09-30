"""Synthetic reviewed DOM, not a claim of live source freshness or AI quality."""
from src.lab_context import (
    NIELSEN_HOME,
    NIELSEN_PROFILE,
    NIELSEN_RECORD_ID,
    NIELSEN_RESEARCH,
    NIELSEN_ROLE,
    NIELSEN_TEAM,
)


def nielsen_record():
    return {'id': NIELSEN_RECORD_ID, 'school':'ucb', 'source':'ucb_stat_faculty', 'source_type':'faculty_research',
            'department':'Department of Statistics', 'pi_name':'Rasmus Nielsen',
            'source_url':NIELSEN_PROFILE, 'url':NIELSEN_PROFILE, 'metadata':{}}


def nielsen_pages():
    profile='''<html><head><title>Rasmus Nielsen | Department of Statistics</title></head><body>
<article class="node node--type-faculty node--view-mode-full"><div class="node__content">
<div class="node_top"><div class="node_top_copy"><h1 class="page--title">Rasmus Nielsen</h1></div></div>
<div class="node_columns"><div class="field field--name-field-website"><div class="field__label">Website</div>
<div class="field__item"><a href="https://nielsen-lab.github.io">https://nielsen-lab.github.io</a></div></div></div>
<div class="field--name-field-research-interests"><div class="field__label">Research interests</div>
<div class="field__item"><p>Statistical methods for population genetics.</p></div></div>
</div></article></body></html>'''
    nav='''<div id="header"><nav class="navbar navbar-expand-md navbar-light bg-navbar"><div class="container">
<div class="collapse navbar-collapse" id="navbarNav"><ul class="navbar-nav nav-pills ml-auto">
<li class="nav-link"><a class="mx-1" href="/research/">Research</a></li>
<li class="nav-link"><a class="mx-1" href="/team/">Team</a></li>
<li class="nav-link"><a class="mx-1" href="/papers/">Papers</a></li>
<li class="nav-link"><a class="mx-1" href="/join/">Join</a></li>
</ul></div></div></nav></div>'''
    home='<html><head><title>Nielsen Lab</title></head><body>'+nav+'<main>Homepage introduction.</main></body></html>'
    team='''<html><head><title>Nielsen Lab / team</title></head><body>'''+nav+'''<div class="container mt-4">
<div class="row"><div class="col-lg-12"><div class="title">Current members</div></div></div>
<div class="row"><div class="col-lg-4 memberbox"><div class="media">
<a class="float-left" href="/team/rasmus-nielsen/"><img src="/photo.jpg"></a><div class="media-body">
<div class="head mb-1"><a class="off" href="/team/rasmus-nielsen/">Rasmus Nielsen</a></div>
<p class="note">'''+NIELSEN_ROLE+'''</p></div></div></div></div>
<div class="row"><div class="col-lg-12"><div class="title">Recent past members</div></div></div>
</div></body></html>'''
    sections=[]
    for i in range(1,11):
        prose=f'Target lab research section {i}. We do not claim clinical validation; 12 samples remain limited.'
        if i==10:
            prose='TENTH_SECTION_MARKER: We study somatic mutations and tumor evolution. We do not establish student expertise.'
        sections.append(f'<h1>Research theme {i}</h1><hr><img src="/research.jpg">{prose} <a href="https://papers.example.org/">Complete inline source words.</a><div class="bigspacer"></div><h4>Example Papers</h4><ol><li><a href="/pdfs/example.pdf">Example paper title {i}</a></li></ol><div class="bigspacer"></div>')
    research='<html><head><title>Nielsen Lab / research</title></head><body>'+nav+'<div class="container mt-4">'+''.join(sections)+'</div></body></html>'
    return {NIELSEN_PROFILE:profile.encode(),NIELSEN_HOME:home.encode(),NIELSEN_TEAM:team.encode(),NIELSEN_RESEARCH:research.encode()}


def nielsen_fetch(pages=None):
    values=nielsen_pages() if pages is None else pages
    def read(url):
        if url not in values:
            raise AssertionError('Unexpected source URL')
        return {'requested_url':url,'source_url':url,'html':values[url]},None
    return read
