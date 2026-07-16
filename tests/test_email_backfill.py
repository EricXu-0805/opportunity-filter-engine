"""Tests for the school-specific email backfill routes (Stanford constructed
SUNet + Princeton Wayback). All network is monkeypatched; the value under test
is the accuracy gating — the displayName gate on the Stanford CAP route, the
personal-email picker on Wayback snapshots, provenance stamping on apply, and
the carry-forward of the provenance flag across re-scrapes.
"""
import json

from src.collectors import email_backfill as eb


class _Resp:
    def __init__(self, status=200, text="", payload=None):
        self.status_code = status
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_stanford_constructs_from_uid_with_name_gate(monkeypatch):
    def _fake_get(url, **kw):
        if url == "https://profiles.stanford.edu/adam-boies":
            return _Resp(text='src="proxy/api/cap/profiles/333038/resources/profilephoto"')
        if url.endswith("/cap/profiles/333038"):
            return _Resp(payload={"data": {"uid": "aboies", "displayName": "Adam Boies",
                                           "email": None}})
        return _Resp(status=404)
    monkeypatch.setattr(eb, "_get", _fake_get)
    out = eb.stanford_email_for("Adam Boies", "https://me.stanford.edu/people/adam-boies")
    assert out == {"email": "aboies@stanford.edu", "uid": "aboies",
                   "display_name": "Adam Boies", "source": "constructed_sunetid"}


def test_stanford_rejects_wrong_person_slug_collision(monkeypatch):
    # A dept slug resolving to a DIFFERENT person's Stanford profile must be
    # rejected by the displayName gate — never construct someone else's address.
    def _fake_get(url, **kw):
        if "profiles.stanford.edu/j" in url and "cap" not in url:
            return _Resp(text='src="proxy/api/cap/profiles/111/resources/profilephoto"')
        if url.endswith("/cap/profiles/111"):
            return _Resp(payload={"data": {"uid": "jsmith2", "displayName": "Jane Smith"}})
        return _Resp(status=404)
    monkeypatch.setattr(eb, "_get", _fake_get)
    assert eb.stanford_email_for("John Smith", "https://me.stanford.edu/people/j-smith") is None
    assert eb.stanford_email_for("Jane Doe", "https://me.stanford.edu/people/j-doe") is None


def test_princeton_wayback_picks_personal_email(monkeypatch):
    def _fake_get(url, **kw):
        if "cdx" in url:
            return _Resp(payload=[["urlkey", "timestamp"],
                                  ["x", "20150101000000"],
                                  ["x", "20170916081638"],
                                  ["x", "20260218135600"]])
        if "20170916081638id_" in url:
            return _Resp(text='Contact: <a href="mailto:aizenman@Princeton.EDU">email</a> '
                              'or <a href="mailto:web@math.princeton.edu">webmaster</a>')
        return _Resp(status=404)
    monkeypatch.setattr(eb, "_get", _fake_get)
    monkeypatch.setattr(eb.time, "sleep", lambda s: None)
    out = eb.princeton_wayback_email_for(
        "Michael Aizenman", "https://phy.princeton.edu/people/michael-aizenman")
    assert out is not None
    assert out["email"] == "aizenman@princeton.edu"
    assert out["source"] == "wayback"


def test_princeton_wayback_rejects_webmaster_only_snapshot(monkeypatch):
    # Live smoke caught this: De Lellis' archived math page carries ONLY
    # www@math.princeton.edu (the webmaster) — the single-candidate fallback
    # must not adopt it as his address.
    def _fake_get(url, **kw):
        if "cdx" in url:
            return _Resp(payload=[["urlkey", "timestamp"], ["x", "20191215202856"]])
        return _Resp(text='<a href="mailto:www@math.princeton.edu">contact</a>')
    monkeypatch.setattr(eb, "_get", _fake_get)
    monkeypatch.setattr(eb.time, "sleep", lambda s: None)
    assert eb.princeton_wayback_email_for(
        "Camillo De Lellis", "https://www.math.princeton.edu/people/camillo-de-lellis") is None


def test_princeton_wayback_no_email_in_snapshots(monkeypatch):
    def _fake_get(url, **kw):
        if "cdx" in url:
            return _Resp(payload=[["urlkey", "timestamp"], ["x", "20240101000000"]])
        return _Resp(text="redesigned page with no contact info")
    monkeypatch.setattr(eb, "_get", _fake_get)
    monkeypatch.setattr(eb.time, "sleep", lambda s: None)
    assert eb.princeton_wayback_email_for("Dmitry Abanin",
                                          "https://phy.princeton.edu/people/dmitry-abanin") is None


class TestUiucNetidConstruction:
    def test_constructs_modern_and_legacy_netids(self):
        ece = {"pi_name": "Rainer Engelken", "school": "uiuc", "source": "uiuc_faculty",
               "url": "https://ece.illinois.edu/about/directory/faculty/engelken"}
        legacy = {"pi_name": "Bruce Hajek", "school": "uiuc", "source": "uiuc_faculty",
                  "url": "https://ece.illinois.edu/about/directory/faculty/b-hajek"}
        cee = {"pi_name": "Imad Al-Qadi", "school": "uiuc", "source": "uiuc_faculty",
               "url": "https://cee.illinois.edu/directory/profile/alqadi"}
        assert eb.uiuc_netid_email_for(ece)["email"] == "engelken@illinois.edu"
        assert eb.uiuc_netid_email_for(legacy)["email"] == "b-hajek@illinois.edu"
        out = eb.uiuc_netid_email_for(cee)
        assert out == {"email": "alqadi@illinois.edu", "netid": "alqadi",
                       "source": "constructed_netid"}

    def test_rejects_name_slugs_and_foreign_hosts(self):
        # firstname-lastname slug (iSchool style) — 65% global accuracy is why
        # construction is gated to netid shapes; this must never construct.
        name_slug = {"pi_name": "Masooda Bashir", "school": "uiuc", "source": "uiuc_faculty",
                     "url": "https://ece.illinois.edu/about/directory/faculty/masooda-bashir"}
        other_host = {"pi_name": "Jessie Chin", "school": "uiuc", "source": "uiuc_faculty",
                      "url": "https://ischool.illinois.edu/people/jessie-chin"}
        long_slug = {"pi_name": "X", "school": "uiuc", "source": "uiuc_faculty",
                     "url": "https://ece.illinois.edu/about/directory/faculty/verylongslugname"}
        assert eb.uiuc_netid_email_for(name_slug) is None
        assert eb.uiuc_netid_email_for(other_host) is None
        assert eb.uiuc_netid_email_for(long_slug) is None

    def test_construct_uiuc_is_updates_only_and_stamps_provenance(self):
        opps = [
            {"pi_name": "Rainer Engelken", "school": "uiuc", "source": "uiuc_faculty",
             "url": "https://ece.illinois.edu/about/directory/faculty/engelken"},
            {"pi_name": "Klara Nahrstedt", "school": "uiuc", "source": "uiuc_faculty",
             "url": "https://ece.illinois.edu/about/directory/faculty/klara",
             "contact_email": "klara@illinois.edu"},
            {"pi_name": "Jane Doe", "school": "uw", "source": "uw_faculty",
             "url": "https://ece.illinois.edu/about/directory/faculty/jdoe"},
        ]
        n = eb.construct_uiuc(opps)
        assert n == 1
        assert opps[0]["contact_email"] == "engelken@illinois.edu"
        assert opps[0]["metadata"]["email_source"] == "constructed_netid"
        # existing email untouched, no provenance stamp added
        assert opps[1]["contact_email"] == "klara@illinois.edu"
        assert "email_source" not in (opps[1].get("metadata") or {})
        # non-uiuc record never constructed even on a matching host
        assert "contact_email" not in opps[2]


def test_apply_stamps_provenance_and_is_updates_only():
    opps = [
        {"pi_name": "A", "school": "stanford", "source": "stanford_faculty",
         "url": "https://me.stanford.edu/people/a"},
        {"pi_name": "B", "school": "stanford", "source": "stanford_faculty",
         "url": "https://me.stanford.edu/people/b", "contact_email": "existing@stanford.edu"},
    ]
    mapping = {
        "https://me.stanford.edu/people/a": {"email": "auid@stanford.edu",
                                             "source": "constructed_sunetid"},
        "https://me.stanford.edu/people/b": {"email": "nope@stanford.edu",
                                             "source": "constructed_sunetid"},
    }
    n = eb.apply_backfill(opps, mapping)
    assert n == 1
    assert opps[0]["contact_email"] == "auid@stanford.edu"
    assert opps[0]["metadata"]["email_source"] == "constructed_sunetid"
    assert opps[1]["contact_email"] == "existing@stanford.edu"
    assert "email_source" not in (opps[1].get("metadata") or {})


def test_harvest_checkpoints_misses_and_resumes(monkeypatch, tmp_path):
    opps = [
        {"pi_name": f"P{i} Roe", "school": "stanford", "source": "stanford_faculty",
         "url": f"https://me.stanford.edu/people/p{i}"}
        for i in range(3)
    ]
    ckpt = str(tmp_path / "st.json")
    monkeypatch.setattr(eb, "stanford_email_for", lambda *a, **k: None)
    monkeypatch.setattr(eb.time, "sleep", lambda s: None)
    assert eb.harvest(opps, "stanford", checkpoint_path=ckpt, throttle=0) == {}
    assert len(json.load(open(ckpt + ".misses"))) == 3

    calls = []
    monkeypatch.setattr(eb, "stanford_email_for", lambda *a, **k: calls.append(1))
    eb.harvest(opps, "stanford", checkpoint_path=ckpt, resume=True, throttle=0)
    assert calls == []


def test_carry_forward_keeps_email_source():
    from src.collectors.uiuc_faculty import _carry_forward_enrichment
    existing = {"contact_email": "aboies@stanford.edu", "keywords": ["nanoparticles"],
                "metadata": {"email_source": "constructed_sunetid"}}
    incoming = {"keywords": [], "metadata": {"last_seen_at": "2026-07-10"}}
    _carry_forward_enrichment(existing, incoming)
    assert incoming["contact_email"] == "aboies@stanford.edu"
    assert incoming["metadata"]["email_source"] == "constructed_sunetid"
    # a fresh scrape that carries its OWN email wins — no flag is stamped
    incoming2 = {"contact_email": "new@stanford.edu", "keywords": [], "metadata": {}}
    _carry_forward_enrichment(existing, incoming2)
    assert incoming2["contact_email"] == "new@stanford.edu"
    assert "email_source" not in incoming2["metadata"]
