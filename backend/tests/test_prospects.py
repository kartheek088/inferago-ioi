"""Prospect finder: OSM parsing, scoring, website audit, API workflow. No live network."""

import httpx

from app import jobs
from app.models import Prospect, ProspectRun
from app.prospects import OVERPASS_ENDPOINTS, audit_html, evaluate, parse_element, pitch, resolve_area

EP = OVERPASS_ENDPOINTS[0]

ELEMENTS = [
    {"type": "node", "id": 1, "lat": 11.01, "lon": 76.95,
     "tags": {"name": "Smile Dental Care", "amenity": "dentist", "phone": "+91 98430 12345", "opening_hours": "Mo-Sa 10:00-20:00",
              "addr:street": "DB Road", "addr:city": "Coimbatore"}},
    {"type": "node", "id": 2, "lat": 11.02, "lon": 76.96,
     "tags": {"name": "Annapoorna Mess", "amenity": "restaurant", "phone": "0422 2222222", "website": "https://facebook.com/annapoornamess"}},
    {"type": "way", "id": 3, "center": {"lat": 11.03, "lon": 76.97},
     "tags": {"name": "Sri Lakshmi Textiles Pvt Ltd", "office": "company", "phone": "0422 3333333", "website": "http://lakshmitex.example"}},
    {"type": "node", "id": 4, "tags": {"name": "Big Chain Pharmacy", "amenity": "pharmacy", "brand": "BigChain", "phone": "1"}},
    {"type": "node", "id": 5, "tags": {"name": "Govt Office", "office": "government", "phone": "1"}},
    {"type": "node", "id": 6, "tags": {"name": "R. Kumar & Associates", "office": "lawyer", "email": "kumar@law.example"}},
    {"type": "node", "id": 7, "tags": {"amenity": "restaurant", "phone": "1"}},  # no name
]


def test_parse_skips_chains_government_and_unnamed():
    parsed = [parse_element(e) for e in ELEMENTS]
    names = [p.name for p in parsed if p]
    assert names == ["Smile Dental Care", "Annapoorna Mess", "Sri Lakshmi Textiles Pvt Ltd", "R. Kumar & Associates"]


def test_social_page_is_not_a_website_and_segments():
    mess = parse_element(ELEMENTS[1])
    assert mess.website is None and mess.social == ["https://facebook.com/annapoornamess"]
    assert parse_element(ELEMENTS[2]).biz.segment == "enterprise"
    assert parse_element(ELEMENTS[5]).biz.segment == "professional"
    assert parse_element(ELEMENTS[0]).biz.segment == "professional"


def test_area_resolution():
    assert resolve_area("coimbatore")[0] == "Coimbatore"
    name, lat, lon, country = resolve_area("Ooty@11.41,76.70")
    assert (name, lat, lon, country) == ("Ooty", 11.41, 76.70, None)  # country never guessed
    for bad in ("Atlantis", "X@200,10"):
        try:
            resolve_area(bad)
            raise AssertionError("should fail")
        except ValueError:
            pass


def test_score_is_explained_and_no_website_ranks_high():
    p = Prospect(name="X", segment="professional", business_type="amenity=dentist", type_label="Dentist", has_website=False,
                 phone="98430 12345", country="India", social_links=[], audit={}, opening_hours="Mo-Fr", address="A")
    evaluate(p)
    assert p.score == 35 + 20 + 15 + 5 + 5
    assert any("no website" in r for r in p.score_reasons)
    assert p.recommended_services[0] == "website"
    assert {g["key"] for g in p.gaps} == {"no_website"}


def test_audit_html_finds_gaps():
    old = "<html><head><title>Lakshmi Tex</title></head><body>© 2015 Lakshmi</body></html>"
    keys = {g["key"] for g in audit_html("http://lakshmitex.example/", old, 2026)}
    assert {"no_https", "not_mobile", "no_description", "no_analytics", "no_chat", "no_form", "outdated"} <= keys
    good = ('<html><head><title>Great Clinic Chennai</title><meta name="viewport" content="width=device-width">'
            '<meta name="description" content="Best dental clinic in Chennai with 20 years experience">'
            '<meta property="og:title" content="x"><script type="application/ld+json">{}</script>'
            '<script src="https://www.googletagmanager.com/gtag/js"></script></head>'
            '<body><form></form><a href="https://wa.me/919999999999">Chat</a>© 2026</body></html>')
    assert audit_html("https://clinic.example/", good, 2026) == []


def test_pitch_is_a_draft_with_links():
    p = Prospect(name="Smile Dental Care", country="India", phone="+91 98430 12345", has_website=False,
                 gaps=[{"key": "no_website", "label": "No website", "detail": ""}], recommended_services=["website", "crm", "ai"],
                 source_url="https://www.openstreetmap.org/node/1")
    d = pitch(p)
    assert "does not have a website" in d["message"]
    assert d["links"]["whatsapp"].startswith("https://wa.me/919843012345?text=")
    assert d["links"]["call"] == "tel:+919843012345"
    assert d["links"]["email"] is None  # never guessed
    assert "Nothing is sent" in d["note"]


def _sync_jobs(monkeypatch):
    def run_now(run_id, *, radius_m, max_per_area, rules=None):
        jobs._run_prospect_search(run_id, radius_m, max_per_area, rules)

    monkeypatch.setattr(jobs, "submit_prospect_search", run_now)


def test_find_api_end_to_end(client, db, web, monkeypatch):
    _sync_jobs(monkeypatch)
    client.put("/api/settings", json={"prospect_only_no_website": False, "prospect_require_phone": False})
    web.json(EP, {"elements": ELEMENTS})
    r = client.post("/api/prospects/find", json={"areas": ["Coimbatore"]})
    assert r.status_code == 202, r.text
    run = db.query(ProspectRun).one()
    db.refresh(run)
    assert run.status == "success" and run.new == 4 and run.found == 4

    page = client.get("/api/prospects").json()
    assert page["total"] == 4
    top = page["items"][0]
    assert top["name"] == "Smile Dental Care" and top["source_url"] == "https://www.openstreetmap.org/node/1"
    assert top["area"] == "Coimbatore" and top["country"] == "India"
    assert client.get("/api/prospects", params={"segment": "enterprise"}).json()["total"] == 1
    assert client.get("/api/prospects", params={"has_website": "false"}).json()["total"] == 3
    assert client.get("/api/prospects", params={"service": "erp"}).json()["total"] == 1

    # re-run: updates, no duplicates, keeps owner status
    client.patch(f"/api/prospects/{top['id']}", json={"status": "shortlisted", "notes": "call Monday"})
    client.post("/api/prospects/find", json={"areas": ["Coimbatore"]})
    assert client.get("/api/prospects").json()["total"] == 4
    assert client.get(f"/api/prospects/{top['id']}").json()["status"] == "shortlisted"

    summary = client.get("/api/prospects/summary").json()
    assert summary["total"] == 4 and summary["no_website"] == 3
    assert "Coimbatore" in client.get("/api/prospects/areas").json()["groups"]["Tamil Nadu"]
    csv_text = client.get("/api/prospects/export.csv").text
    assert "Smile Dental Care" in csv_text.splitlines()[1]


def test_website_audit_and_contact_log(client, db, web, monkeypatch):
    _sync_jobs(monkeypatch)
    client.put("/api/settings", json={"prospect_only_no_website": False, "prospect_require_phone": False})
    web.json(EP, {"elements": ELEMENTS})
    web.text("http://lakshmitex.example/", "<html><head><title>Lakshmi Tex</title></head><body>© 2016</body></html>")
    client.post("/api/prospects/find", json={"areas": ["Coimbatore"]})
    ent = client.get("/api/prospects", params={"segment": "enterprise"}).json()["items"][0]
    before = ent["score"]
    r = client.post(f"/api/prospects/{ent['id']}/audit")
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["score"] > before and any(g["key"] == "outdated" for g in after["gaps"])

    no_site = client.get("/api/prospects", params={"has_website": "false"}).json()["items"][0]
    assert client.post(f"/api/prospects/{no_site['id']}/audit").status_code == 422

    r = client.post(f"/api/prospects/{no_site['id']}/contact", json={"channel": "whatsapp", "outcome": "contacted", "note": "sent intro"})
    body = r.json()
    assert body["status"] == "contacted" and body["next_follow_up"] and len(body["contact_log"]) == 1


def test_failed_endpoints_mark_run_failed(client, db, web, monkeypatch):
    _sync_jobs(monkeypatch)
    for ep in OVERPASS_ENDPOINTS:
        web.error(ep, 504)
    client.post("/api/prospects/find", json={"areas": ["Coimbatore"]})
    run = db.query(ProspectRun).one()
    db.refresh(run)
    assert run.status == "failed" and run.found == 0 and any("504" in line for line in run.log)


def test_unknown_area_rejected(client):
    assert client.post("/api/prospects/find", json={"areas": ["Atlantis"]}).status_code == 422


def test_overpass_robots_respected(web):
    """The query must go through SafeHttp's robots.txt check like every other request."""
    from app.http_client import RobotsDisallowedError, SafeHttp
    from app.prospects import fetch_area

    web.routes[EP.split("/api/")[0] + "/robots.txt"] = lambda req: httpx.Response(200, text="User-agent: *\nDisallow: /api/")
    http = SafeHttp()
    try:
        fetch_area(http, 1.0, 1.0, 1000, endpoints=[EP])
        raise AssertionError("should be blocked")
    except Exception as exc:  # noqa: BLE001
        assert "robots" in str(exc).lower() or isinstance(exc, RobotsDisallowedError)


def test_enterprise_leads_with_erp():
    p = Prospect(name="Kovai Engineering Industries", segment="enterprise", business_type="industrial=*", type_label="Factory",
                 has_website=False, phone="1", social_links=[], audit={})
    evaluate(p)
    assert p.recommended_services[0] == "erp" and "website" in p.recommended_services


def test_dead_servers_end_run_early_and_progress_is_logged(client, db, web, monkeypatch):
    _sync_jobs(monkeypatch)
    for ep in OVERPASS_ENDPOINTS:
        web.error(ep, 504)
    client.post("/api/prospects/find", json={"areas": ["Chennai", "Coimbatore", "Madurai", "Salem"]})
    run = db.query(ProspectRun).one()
    db.refresh(run)
    assert run.status == "failed"
    # every mirror is tried once, then the run stops instead of waiting on dead servers city after city
    assert sum("/api/interpreter" in c for c in web.calls) == len(OVERPASS_ENDPOINTS)
    assert any("ended early" in line for line in run.log)


def test_stop_request(client, db, web, monkeypatch):
    web.json(EP, {"elements": ELEMENTS})
    monkeypatch.setattr(jobs, "submit_prospect_search", lambda *a, **k: None)  # leave it "running"
    run_id = client.post("/api/prospects/find", json={"areas": ["Chennai", "Coimbatore"]}).json()["id"]
    assert client.post("/api/prospects/find", json={"areas": ["Chennai"]}).status_code == 409
    assert client.post(f"/api/prospects/runs/{run_id}/stop").json()["status"] == "stopping"
    jobs._run_prospect_search(run_id, 3000, 80)
    run = db.get(ProspectRun, run_id)
    db.refresh(run)
    assert run.status == "stopped" and run.found == 0 and "Stopped by you." in run.log


def _write_pbf(path):
    import osmium

    w = osmium.SimpleWriter(str(path))
    try:
        w.add_node(osmium.osm.mutable.Node(id=1, location=(76.955, 11.017), version=1,
                   tags={"name": "Smile Dental Care", "amenity": "dentist", "phone": "+91 98430 12345"}))
        w.add_node(osmium.osm.mutable.Node(id=2, location=(76.96, 11.02), version=1,
                   tags={"name": "No Contact Shop", "shop": "clothes"}))  # unreachable → skipped
        w.add_node(osmium.osm.mutable.Node(id=3, location=(-0.12, 51.5), version=1,
                   tags={"name": "London Cafe", "amenity": "cafe", "phone": "1"}))  # outside Tamil Nadu box
        w.add_node(osmium.osm.mutable.Node(id=4, location=(80.27, 13.08), version=1, tags={"name": "Chain", "shop": "x", "brand": "B", "phone": "1"}))
        for i, (lon, lat) in enumerate([(80.27, 13.08), (80.271, 13.08), (80.271, 13.081), (80.27, 13.08)], 10):
            w.add_node(osmium.osm.mutable.Node(id=i, location=(lon, lat), version=1))
        w.add_way(osmium.osm.mutable.Way(id=100, nodes=[10, 11, 12, 13], version=1,
                  tags={"name": "Hotel Marina", "tourism": "hotel", "phone": "044 1234567"}))
    finally:
        w.close()


def test_map_file_scan(client, db, monkeypatch, tmp_path):
    from app.api import prospects as api_mod

    maps = tmp_path / "maps"
    maps.mkdir()
    _write_pbf(maps / "test-latest.osm.pbf")
    monkeypatch.setattr(api_mod, "map_folders", lambda: {"maps": maps, "downloads": tmp_path / "none"})
    monkeypatch.setattr(api_mod, "_still_downloading", lambda f: False)
    monkeypatch.setattr(jobs, "submit_map_scan", lambda run_id, path, **kw: jobs._run_map_scan(run_id, path, kw))

    files = client.get("/api/prospects/map-files").json()["files"]
    assert [f["file"] for f in files] == ["test-latest.osm.pbf"]
    r = client.post("/api/prospects/scan-map-file", json={"folder": "maps", "file": "test-latest.osm.pbf", "region": "Tamil Nadu"})
    assert r.status_code == 202, r.text
    run = db.get(ProspectRun, r.json()["id"])
    db.refresh(run)
    assert run.status == "success", run.log
    items = {p["name"]: p for p in client.get("/api/prospects", params={"status": ""}).json()["items"]}
    assert set(items) == {"Smile Dental Care", "Hotel Marina"}
    assert items["Smile Dental Care"]["area"] == "Coimbatore" and items["Smile Dental Care"]["country"] == "India"
    assert items["Hotel Marina"]["area"] == "Chennai" and items["Hotel Marina"]["source_url"].endswith("/way/100")

    # only listed folders and plain file names are accepted
    assert client.post("/api/prospects/scan-map-file", json={"folder": "maps", "file": "../x.osm.pbf"}).status_code == 422
    assert client.post("/api/prospects/scan-map-file", json={"folder": "etc", "file": "a.osm.pbf"}).status_code == 422
    assert client.post("/api/prospects/scan-map-file", json={"folder": "maps", "file": "missing.osm.pbf"}).status_code == 404


def test_map_file_scan_city_radius(db, tmp_path):
    from app.prospects import run_map_file_scan

    _write_pbf(tmp_path / "t.osm.pbf")
    run = ProspectRun(areas=["map file"], status="running", log=[])
    db.add(run)
    db.commit()
    run_map_file_scan(db, run, str(tmp_path / "t.osm.pbf"), region="Whole file", max_keep=100, cities=["Chennai"], radius_km=10)
    assert run.status == "success" and run.found == 1
    assert db.query(Prospect).one().name == "Hotel Marina"


def test_check_phone():
    from app.prospects import check_phone

    assert check_phone("+91 98430 12345", "India") == ("+919843012345", "mobile")
    assert check_phone("09843012345", "India") == ("+919843012345", "mobile")
    assert check_phone("0422 2540400", "India") == ("+914222540400", "landline")
    assert check_phone("91-422-2540400", "India") == ("+914222540400", "landline")
    assert check_phone("12345; 9486255032", "India") == ("+919486255032", "mobile")  # first valid wins
    assert check_phone("1800 425 1234", "India")[1] == "toll_free"
    assert check_phone("12345", "India") == (None, "invalid")
    assert check_phone("+44 20 7946 0958", "United Kingdom") == ("+442079460958", "international")
    assert check_phone(None, "India") == (None, None)


def test_new_searches_skip_websites_and_bad_phones_but_keep_old(client, db, web, monkeypatch):
    _sync_jobs(monkeypatch)
    old = Prospect(name="Old With Site", segment="small_business", business_type="shop=clothes", type_label="Clothes", has_website=True,
                   website="https://old.example", source_ref="osm:node/999", source_url="https://www.openstreetmap.org/node/999",
                   social_links=[], audit={}, gaps=[], recommended_services=[], score_reasons=[], contact_log=[], raw_tags={})
    db.add(old)
    db.commit()
    els = ELEMENTS + [{"type": "node", "id": 50, "tags": {"name": "Bad Phone Salon", "shop": "hairdresser", "phone": "123"}}]
    web.json(EP, {"elements": els})
    client.post("/api/prospects/find", json={"areas": ["Coimbatore"]})
    names = {p["name"] for p in client.get("/api/prospects", params={"status": "", "limit": 100}).json()["items"]}
    # Lakshmi Textiles (website) and Kumar & Associates (email only) and Bad Phone Salon are skipped; old one kept
    assert names == {"Old With Site", "Smile Dental Care", "Annapoorna Mess"}
    run = db.query(ProspectRun).one()
    db.refresh(run)
    assert "has a website" in run.log[-1] and "no usable phone number" in run.log[-1]

    smile = client.get("/api/prospects", params={"q": "Smile"}).json()["items"][0]
    assert smile["phone_type"] == "mobile" and smile["phone_normalized"] == "+919843012345" and not smile["phone_verified"]
    assert client.get("/api/prospects", params={"phone": "mobile"}).json()["total"] == 1
    r = client.post(f"/api/prospects/{smile['id']}/phone-verified").json()
    assert r["phone_verified"] and r["score"] > smile["score"]
    assert client.get("/api/prospects", params={"phone": "verified"}).json()["total"] == 1


def test_answered_call_verifies_phone(client, db, web, monkeypatch):
    _sync_jobs(monkeypatch)
    web.json(EP, {"elements": ELEMENTS})
    client.post("/api/prospects/find", json={"areas": ["Coimbatore"]})
    pid = client.get("/api/prospects", params={"q": "Smile"}).json()["items"][0]["id"]
    assert not client.post(f"/api/prospects/{pid}/contact", json={"channel": "call", "outcome": "contacted"}).json()["phone_verified"]
    assert client.post(f"/api/prospects/{pid}/contact", json={"channel": "call", "outcome": "interested"}).json()["phone_verified"]


def test_rules_can_be_turned_off(client, db, web, monkeypatch):
    _sync_jobs(monkeypatch)
    client.put("/api/settings", json={"prospect_only_no_website": False, "prospect_require_phone": False})
    web.json(EP, {"elements": ELEMENTS})
    client.post("/api/prospects/find", json={"areas": ["Coimbatore"]})
    assert client.get("/api/prospects", params={"status": ""}).json()["total"] == 4


# --- exclusions & need level --------------------------------------------------------------------

def test_exclusions():
    from app.prospects import exclusion_reason as ex

    assert ex({}, "OYO 81234 Hotel Sri Lakshmi", "tourism=hotel") == "part of a chain or partner network"
    assert ex({}, "Sri Krishna Engineering College", "amenity=school") == "college or university"
    assert ex({}, "Sanrad Infotech", "office=company") == "IT / software company"
    assert ex({}, "TTDC Hotel Tamil Nadu", "tourism=hotel") == "government"
    assert ex({"brand": "X"}, "Any Shop", "shop=clothes") == "part of a chain or brand"
    for ok in ("Taj Lodge", "Kalyan Mahal", "Smile Dental Care", "Narayana Medicals", "Sri Murugan Silks"):
        assert ex({}, ok, "amenity=restaurant") is None, ok


def test_need_levels():
    def mk(**kw):
        base = dict(name="X", segment="professional", business_type="amenity=dentist", type_label="Dentist", has_website=False,
                    phone="9843012345", country="India", social_links=[], audit={}, address="DB Road")
        base.update(kw)
        p = Prospect(**base)
        evaluate(p)
        return p

    assert mk().need_level == "definite"
    assert mk(address=None).need_level == "likely"  # no sign it is active
    assert mk(business_type="shop=gift", segment="small_business").need_level == "likely"  # low-value type
    assert mk(phone="123").need_level == "maybe"
    assert mk(has_website=True, website="https://x.example").need_level == "maybe"


def test_need_filter_api(client, db, web, monkeypatch):
    _sync_jobs(monkeypatch)
    web.json(EP, {"elements": ELEMENTS})
    client.post("/api/prospects/find", json={"areas": ["Coimbatore"]})
    definite = client.get("/api/prospects", params={"need": "definite"}).json()["items"]
    assert {p["name"] for p in definite} == {"Smile Dental Care", "Annapoorna Mess"}  # mess: active on social media
    assert all("no website" in p["need_reasons"] for p in definite)
    assert client.get("/api/prospects/summary").json()["definite"] == 2


# --- big projects -------------------------------------------------------------------------------

def test_analyse_headlines():
    from app.big_projects import analyse

    m = analyse("Waaree Transpower bags over ₹100 crore NTPC order for battery storage project", "")
    assert m.project_type == "contract_won" and m.company == "Waaree Transpower" and m.amount.startswith("₹100")
    m = analyse("Ashok Leyland to set up truck plant near Hosur", "")
    assert m.project_type == "new_facility" and m.location == "Hosur" and any("Tamil Nadu" in r for r in m.reasons)
    assert analyse("PMK urges Tamil Nadu govt. to secure interim stay on HC order", "") is None
    assert analyse("Sensex jumps 500 points as banks rally", "") is None
    assert analyse("Weather update for Chennai", "Rain likely") is None


RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Kovai Pumps bags ₹250 crore order from Saudi utility</title><link>https://news.example/a</link>
<description>The Coimbatore-based firm will deliver over two years.</description><pubDate>{d}</pubDate></item>
<item><title>Sensex falls 300 points</title><link>https://news.example/b</link><description>x</description><pubDate>{d}</pubDate></item>
</channel></rss>"""


def test_big_projects_api(client, web):
    from email.utils import format_datetime
    from datetime import UTC, datetime

    from app.big_projects import DEFAULT_FEEDS

    d = format_datetime(datetime.now(UTC))
    feeds = list(DEFAULT_FEEDS.values())
    web.text(feeds[0], RSS.format(d=d), content_type="application/rss+xml")
    for f in feeds[1:]:
        web.error(f, 503)
    stats = client.post("/api/big-projects/find").json()
    assert stats["new"] == 1 and stats["feeds_ok"] == 1 and len(stats["feeds_failed"]) == len(feeds) - 1
    assert client.post("/api/big-projects/find").json()["new"] == 0  # no duplicates
    items = client.get("/api/big-projects").json()["items"]
    lead = items[0]
    assert lead["company"] == "Kovai Pumps" and lead["location"] == "Coimbatore" and lead["url"] == "https://news.example/a"
    assert client.get("/api/big-projects", params={"near": "tamil_nadu"}).json()["total"] == 1
    a = client.get(f"/api/big-projects/{lead['id']}/approach").json()
    assert "Kovai Pumps" in a["message"] and "Nothing is sent" in " ".join(a["how_to"])
    assert client.patch(f"/api/big-projects/{lead['id']}", json={"status": "rejected"}).json()["status"] == "rejected"
    assert client.get("/api/big-projects").json()["total"] == 0
    assert client.get("/api/big-projects/summary").json()["last_run"]["new"] == 0


def test_project_winner_and_it_skip():
    from app.big_projects import analyse

    assert analyse("JNPA awards 8-yr contract to Gateway Distriparks for rail yard operations", "").company == "Gateway Distriparks"
    assert analyse("Aurionpro secures ₹100 crore order from global hyperscaler", "") is None
    assert analyse("Infosys wins $1.5 billion deal from European bank", "") is None


def test_dealers_allowed_but_chains_not():
    from app.prospects import exclusion_reason as ex

    assert ex({"shop": "car", "brand": "Maruti Suzuki"}, "Sri Vari Maruti Showroom", "shop=car") is None
    assert ex({"shop": "motorcycle", "brand": "Honda"}, "Kovai Honda", "shop=motorcycle") is None
    assert ex({"shop": "clothes", "brand": "Zudio"}, "Zudio", "shop=clothes") == "part of a chain or brand"
    assert ex({"shop": "electronics"}, "Poorvika Mobiles", "shop=electronics") == "part of a chain or partner network"


def test_social_presence_makes_definite_and_owner_check(client, db, web, monkeypatch):
    def mk(**kw):
        base = dict(name="X", segment="small_business", business_type="shop=gift", type_label="Gift", has_website=False,
                    phone="9843012345", country="India", social_links=["https://instagram.com/x"], audit={})
        base.update(kw)
        p = Prospect(**base)
        evaluate(p)
        return p

    p = mk()
    assert p.need_level == "definite" and "no team or know-how" in p.need_reasons[0]
    assert mk(audit={"social_activity": "inactive"}).need_level == "likely"
    assert mk(audit={"social_activity": "very_active"}).score > p.score

    _sync_jobs(monkeypatch)
    web.json(EP, {"elements": ELEMENTS})
    client.post("/api/prospects/find", json={"areas": ["Coimbatore"]})
    mess = client.get("/api/prospects", params={"q": "Annapoorna"}).json()["items"][0]
    r = client.post(f"/api/prospects/{mess['id']}/social-activity", params={"activity": "very_active"}).json()
    assert r["audit"]["social_activity"] == "very_active" and r["score"] > mess["score"]
    assert client.post(f"/api/prospects/{mess['id']}/social-activity").json()["audit"].get("social_activity") is None


def test_place_names_and_more_cities():
    from app.prospects import _place_name, nearest_city

    assert _place_name("tonk") == "Tonk" and _place_name("NEW DELHI, India") == "New Delhi" and _place_name("  ") is None
    assert nearest_city(22.72, 75.86) == ("Indore", "India")
    assert nearest_city(0.0, 0.0) == ("Other", None)
