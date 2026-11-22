"""Overture places → prospects. Uses a small local Parquet file; no network."""

from app import jobs
from app.models import Prospect, ProspectRun
from app.overture import RELEASE_INDEX, classify, latest_release, run_overture_scan, to_parsed

ROWS = [
    # id, name, basic, category, phones, websites, socials, conf, address, locality, brand, lat, lon
    ("a1", "Kovai Smile Dental", "health_care", "dentist", ["+919843012345"], None, ["https://www.facebook.com/kovaismile"], 0.6, "DB Road", "Coimbatore", None, 11.01, 76.95),
    ("a2", "Rani Hospital", "hospital", "hospital", ["+914222347403"], ["https://ranihospital.example"], None, 0.5, None, "Coimbatore", None, 11.02, 76.96),
    ("a3", "PSG College of Technology", "college_university", "college_university", ["+914222572177"], None, None, 0.9, None, "Coimbatore", None, 11.02, 76.99),
    ("a4", "Sri Vari Honda", "shopping", "motorsports_store", ["+919790007107"], None, ["https://www.facebook.com/x"], 0.5, None, "Coimbatore", "Honda", 11.0, 76.9),
    ("a5", "Lahore Sweets", "restaurant", "dessert_shop", ["+92 300 1234567"], None, None, 0.6, None, "Lahore", None, 31.5, 74.3),
    ("a10", "Yangon Tea Shop", "restaurant", "cafe", ["09425320051"], None, ["https://facebook.com/ygn"], 0.6, None, "Yangon", None, 16.8, 96.15),
    ("a6", "Ghost Shop", "shopping", "clothing_store", ["+919876543210"], None, None, 0.1, None, "Chennai", None, 13.08, 80.27),
    ("a7", "Zudio", "shopping", "clothing_store", ["+919876543211"], None, None, 0.8, None, "Chennai", "Zudio", 13.08, 80.27),
    ("a8", "Webtech Infotech", "professional_service", "it_service_and_computer_repair", ["+919876543212"], None, None, 0.8, None, "Chennai", None, 13.08, 80.27),
    ("a9", "FB Only Salon", "beauty_and_spa", "hair_salon", ["+919876543213"], ["https://facebook.com/fbonly"], None, 0.6, None, "Chennai", None, 13.08, 80.27),
]


def _write(path):
    import duckdb

    con = duckdb.connect()
    con.execute("""CREATE TABLE t (id VARCHAR, name VARCHAR, basic_category VARCHAR, category VARCHAR, hierarchy VARCHAR[], phones VARCHAR[],
                   websites VARCHAR[], socials VARCHAR[], emails VARCHAR[], confidence DOUBLE, operating_status VARCHAR, address VARCHAR,
                   locality VARCHAR, region VARCHAR, postcode VARCHAR, country VARCHAR, brand VARCHAR, dataset VARCHAR, lon DOUBLE, lat DOUBLE)""")
    for r in ROWS:
        country = "MM" if r[0] == "a10" else ("PK" if r[0] == "a5" else "IN")
        con.execute("INSERT INTO t VALUES (?, ?, ?, ?, NULL, ?, ?, ?, NULL, ?, NULL, ?, ?, NULL, NULL, ?, ?, 'meta', ?, ?)",
                    [r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], country, r[10], r[12], r[11]])
    con.execute(f"COPY t TO '{path}' (FORMAT parquet)")


def test_classify():
    assert classify("dentist", None, None)[1].label == "Dentist"
    assert classify("college_university", None, None)[1].segment == "college"  # colleges are listed (owner, 2026-11-22)
    assert classify("textile_manufacturer", None, None)[1].segment == "enterprise"
    assert classify("motorsports_store", None, None)[2] == "car"  # dealer


def test_scan_rules(db, tmp_path):
    f = tmp_path / "overture-test.parquet"
    _write(f)
    run = ProspectRun(areas=["Overture: test"], status="running", log=[])
    db.add(run)
    db.commit()
    run_overture_scan(db, run, str(f), max_keep=100)
    assert run.status == "success", run.log
    names = {p.name for p in db.query(Prospect).all()}
    # kept: dentist (social, no site), college, salon whose only "website" is Facebook
    # skipped: hospital (website), Honda dealer (owner: dealers don't work out), Pakistani number, Myanmar listing,
    #          low confidence, Zudio chain, IT company
    assert names == {"Kovai Smile Dental", "PSG College of Technology", "FB Only Salon"}
    assert db.query(Prospect).filter_by(name="PSG College of Technology").one().segment == "college"
    dent = db.query(Prospect).filter_by(name="Kovai Smile Dental").one()
    assert dent.source == "overture" and dent.source_url.startswith("https://explore.overturemaps.org/#17/11.01")
    assert dent.need_level == "definite" and dent.country == "India" and dent.area == "Coimbatore"
    salon = db.query(Prospect).filter_by(name="FB Only Salon").one()
    assert not salon.has_website and salon.social_links == ["https://facebook.com/fbonly"]


def test_scan_cities_and_api(client, db, monkeypatch, tmp_path):
    from app.api import prospects as api_mod

    maps = tmp_path / "maps"
    maps.mkdir()
    _write(maps / "overture-india-test.parquet")
    monkeypatch.setattr(api_mod, "map_folders", lambda: {"maps": maps, "downloads": tmp_path})
    monkeypatch.setattr(jobs, "submit_overture", lambda run_id, action, **kw: jobs._run_overture(run_id, action, kw))
    st = client.get("/api/prospects/overture").json()
    assert [f["file"] for f in st["files"]] == ["overture-india-test.parquet"]
    r = client.post("/api/prospects/scan-overture", json={"file": "overture-india-test.parquet", "cities": ["Chennai"], "radius_km": 10})
    assert r.status_code == 202, r.text
    assert {p["name"] for p in client.get("/api/prospects", params={"status": ""}).json()["items"]} == {"FB Only Salon"}
    assert client.post("/api/prospects/scan-overture", json={"file": "../x.parquet"}).status_code == 422
    assert client.post("/api/prospects/scan-overture", json={"file": "overture-missing.parquet"}).status_code == 404


def test_latest_release(web):
    from app.http_client import SafeHttp

    web.text(RELEASE_INDEX.split("?")[0], "<Prefix>release/2026-10-21.0/</Prefix><Prefix>release/2026-11-18.0/</Prefix>", content_type="application/xml")
    assert latest_release(SafeHttp()) == "2026-11-18.0"


def test_to_parsed_skips_closed():
    row = dict(id="x", name="Closed Cafe", category="cafe", basic_category="restaurant", hierarchy=None, phones=["+919876543210"],
               websites=None, socials=None, emails=None, confidence=0.9, operating_status="permanently_closed", address=None,
               locality=None, postcode=None, brand=None, dataset="meta", lat=13.0, lon=80.0)
    assert to_parsed(row) is None


def test_extra_exclusions():
    from app.overture import extra_exclusion as e

    assert e("Government Medical College", "School", "small_business")
    assert e("TFK Memorial Bible College", "School", "small_business") is None  # colleges are listed now
    assert e("Prism Infotech", "Coaching / training", "small_business") == "IT / software company"
    assert e("Kerala Gramin Bank", "Events / weddings / catering", "small_business") == "bank"
    for ok in [("Sudiksha Prabhu Hospital Blood Bank", "Hospital"), ("Sri Engineering Works", "Manufacturer / wholesaler / logistics"),
               ("College Road Bakery", "Restaurant / cafe / food")]:
        assert e(ok[0], ok[1], "small_business") is None


def test_upgrade_and_college_modes(db, tmp_path):
    f = tmp_path / "overture-test.parquet"
    _write(f)
    run = ProspectRun(areas=["x"], status="running", log=[])
    db.add(run)
    db.commit()
    run_overture_scan(db, run, str(f), max_keep=100, mode="upgrade")
    assert {p.name for p in db.query(Prospect).all()} == {"Rani Hospital"}  # has a real website
    rani = db.query(Prospect).one()
    assert rani.has_website and rani.need_level == "check_site"
    run2 = ProspectRun(areas=["x"], status="running", log=[])
    db.add(run2)
    db.commit()
    run_overture_scan(db, run2, str(f), max_keep=100, mode="colleges")
    assert "PSG College of Technology" in {p.name for p in db.query(Prospect).all()}


def test_chains_build():
    from app.chains import build_chain

    def b(i, city, phone="+919876543210", web=None):
        return {"id": f"x{i}", "name": "Kovai Sweets", "category": "bakery", "basic": "restaurant", "phone": phone, "socials": ["https://facebook.com/kovaisweets"],
                "websites": web, "region": "IN-TN", "city": city, "address": "Main Rd", "lat": 11.0 + i / 10, "lon": 77.0, "conf": 0.6}

    g = {"key": "kovai sweets", "nloc": 4, "nreg": 1, "ncat": 1, "shared": 1, "shared_values": ["+919876543210"],
         "branches": [b(1, "Coimbatore"), b(2, "Tiruppur"), b(3, "Erode"), b(4, "Salem")]}
    c = build_chain(g)
    assert c["branch_count"] == 4 and c["main_state"] == "Tamil Nadu" and c["evidence"] == "shared_contact" and not c["has_website"]
    assert c["phones"] == ["+919876543210"] and len(c["branches"]) == 4 and c["score"] > 60
    bank = {**g, "key": "kovai bank", "branches": [{**x, "name": "Kovai Co-op Bank"} for x in g["branches"]]}
    assert build_chain(bank) is None
    nophone = {**g, "branches": [{**x, "phone": "123"} for x in g["branches"]]}
    assert build_chain(nophone) is None


def test_chains_api(client, db, monkeypatch, tmp_path):
    from app.api import prospects as api_mod
    from app.models import BusinessChain

    db.add(BusinessChain(key="k1", name="Kovai Sweets", type_label="Restaurant / cafe / food", segment="small_business", branch_count=4,
                         cities=["Coimbatore"], states=["Tamil Nadu"], main_state="Tamil Nadu", phones=["+919876543210"], socials=[],
                         has_website=False, evidence="shared_contact", branches=[], services=["website"], score=80, score_reasons=[],
                         status="new", contact_log=[]))
    db.commit()
    d = client.get("/api/multi-branch", params={"state": "Tamil Nadu"}).json()
    assert d["total"] == 1
    cid = d["items"][0]["id"]
    r = client.post(f"/api/multi-branch/{cid}/contact", json={"channel": "call", "outcome": "callback", "callback_at": "2026-12-01T05:00:00"}).json()
    assert r["status"] == "callback" and r["next_follow_up"].startswith("2026-12-01")
    s = client.get("/api/multi-branch/summary").json()
    assert s["total"] == 1 and s["by_state"] == {"Tamil Nadu": 1}
    monkeypatch.setattr(api_mod, "map_folders", lambda: {"maps": tmp_path, "downloads": tmp_path})
    assert client.post("/api/multi-branch/find").status_code == 404  # no directory file yet


def test_new_listing_mode(db, tmp_path):
    import duckdb

    f = tmp_path / "overture-india-2026-11-18.0.parquet"
    _write(f)
    prev = tmp_path / "overture-ids-2026-10-21.0.parquet"
    duckdb.connect().execute(f"COPY (SELECT 'a1' AS id) TO '{prev}' (FORMAT parquet)")  # dentist existed last month
    run = ProspectRun(areas=["x"], status="running", log=[])
    db.add(run)
    db.commit()
    run_overture_scan(db, run, str(f), max_keep=100, mode="new", prev_ids=str(prev))
    names = {p.name for p in db.query(Prospect).all()}
    assert "Kovai Smile Dental" not in names and "FB Only Salon" in names
    assert all(p.new_listing for p in db.query(Prospect).all())
