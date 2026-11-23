"""Where a social seller actually operates.

Social sellers often have no storefront, so a street address is not the only acceptable evidence.
What counts, and how much, is decided by the *basis* of the evidence, not by how often "Chennai"
appears:

  strong  — the business itself states where it operates: a location in its own business profile, an
            address on its own website, a public business registration, or the owner confirming it.
  medium  — the business publishes a Chennai delivery/service area, a Chennai pickup point, or appears
            in a public Chennai market/exhibitor listing. One of these alone is only "probable";
            two independent ones corroborate each other and count as verified.
  weak    — a Chennai hashtag, Tamil-language captions, a Chennai follower, a customer's comment.
            These NEVER raise the confidence, by design. They are recorded and ignored.

Outcomes: verified_chennai | probable_chennai | unclear | outside_chennai.
Only `verified_chennai` can enter the high-priority outreach queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app import chennai

VERIFIED = "verified_chennai"
PROBABLE = "probable_chennai"
UNCLEAR = "unclear"
OUTSIDE = "outside_chennai"

GEO_LABEL = {VERIFIED: "Verified Chennai", PROBABLE: "Probable Chennai", UNCLEAR: "Unclear",
             OUTSIDE: "Outside Chennai"}

# basis -> (strength, plain-language description of what this evidence is)
BASES: dict[str, tuple[str, str]] = {
    "profile_location": ("strong", "location in their own business profile"),
    "official_site": ("strong", "address on their own website"),
    "registration": ("strong", "public business registration"),
    "owner": ("strong", "confirmed by you"),
    "delivery_area": ("medium", "published Chennai delivery/service area"),
    "pickup_point": ("medium", "publicly listed Chennai pickup location"),
    "event_listing": ("medium", "public Chennai market / exhibitor listing"),
    "press": ("medium", "published business feature naming Chennai"),
    # Never sufficient on their own, however many there are.
    "hashtag": ("weak", "a Chennai hashtag"),
    "caption_language": ("weak", "Tamil-language captions"),
    "follower": ("weak", "a Chennai follower"),
    "customer_comment": ("weak", "a customer's comment"),
}
WEAK_NOTE = "Hashtags, caption language, followers and customer comments never count as location evidence."


@dataclass
class GeoEvidence:
    basis: str
    text: str  # the words that state the location
    url: str | None = None
    excerpt: str | None = None

    @property
    def strength(self) -> str:
        return BASES.get(self.basis, ("weak", "unrecognised evidence"))[0]

    @property
    def basis_label(self) -> str:
        return BASES.get(self.basis, ("weak", "unrecognised evidence"))[1]


@dataclass
class GeoVerdict:
    confidence: str
    reason: str
    basis: str | None = None
    locality: str | None = None
    pincode: str | None = None
    evidence_url: str | None = None
    excerpt: str | None = None
    weak_ignored: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return GEO_LABEL[self.confidence]


def classify(items: list[GeoEvidence], *, approved: tuple[str, ...] | list[str] = ()) -> GeoVerdict:
    """Decide the geographic confidence from every piece of evidence gathered so far."""
    weak = [e.basis_label for e in items if e.strength == "weak"]
    usable = [e for e in items if e.strength in ("strong", "medium")]
    if not usable:
        reason = "No location evidence from the business itself yet."
        if weak:
            reason += f" Found only {', '.join(sorted(set(weak)))} — {WEAK_NOTE.lower()}"
        return GeoVerdict(UNCLEAR, reason, weak_ignored=sorted(set(weak)))

    # Evaluate every usable item: what does its text actually say?
    rated: list[tuple[GeoEvidence, chennai.LocationVerdict]] = [
        (e, chennai.classify_location(e.text, approved=approved)) for e in usable
    ]

    # An out-of-city address stated by the business itself settles it.
    for e, v in rated:
        if v.status in (chennai.OUTSIDE, chennai.GCMA_OUTSIDE) and e.strength == "strong":
            return GeoVerdict(OUTSIDE, f"{v.reason} (from their {e.basis_label})", e.basis, v.locality, v.pincode,
                              e.url, e.excerpt or e.text[:300], sorted(set(weak)))

    city = [(e, v) for e, v in rated if v.status == chennai.CHENNAI_CITY]
    strong_city = [(e, v) for e, v in city if e.strength == "strong"]
    medium_city = [(e, v) for e, v in city if e.strength == "medium"]

    if strong_city:
        e, v = strong_city[0]
        return GeoVerdict(VERIFIED, f"{v.reason}, stated in their {e.basis_label}", e.basis, v.locality, v.pincode,
                          e.url, e.excerpt or e.text[:300], sorted(set(weak)))

    # Two independent medium sources corroborate each other (e.g. a delivery area and an event listing).
    if len({e.basis for e, _ in medium_city}) >= 2:
        e, v = medium_city[0]
        others = ", ".join(sorted({x.basis_label for x, _ in medium_city})[:3])
        return GeoVerdict(VERIFIED, f"{v.reason}, corroborated by {len(medium_city)} independent sources ({others})",
                          e.basis, v.locality, v.pincode, e.url, e.excerpt or e.text[:300], sorted(set(weak)))

    if medium_city:
        e, v = medium_city[0]
        return GeoVerdict(PROBABLE, f"{v.reason}, but only from their {e.basis_label} — needs one more independent source",
                          e.basis, v.locality, v.pincode, e.url, e.excerpt or e.text[:300], sorted(set(weak)))

    # The business states a location, but it does not name a locality inside the city limit.
    strong_any = [(e, v) for e, v in rated if e.strength == "strong"]
    if strong_any:
        e, v = strong_any[0]
        return GeoVerdict(PROBABLE, f"Their {e.basis_label} mentions Chennai but names no locality inside the city limit "
                                    f"({v.reason.lower()})", e.basis, v.locality, v.pincode, e.url,
                          e.excerpt or e.text[:300], sorted(set(weak)))

    e, v = rated[0]
    return GeoVerdict(UNCLEAR, f"Location evidence is not specific enough: {v.reason.lower()} (from their {e.basis_label})",
                      e.basis, v.locality, v.pincode, e.url, e.excerpt or e.text[:300], sorted(set(weak)))


def high_priority_ready(confidence: str) -> bool:
    """Only verified businesses enter the high-priority outreach queue."""
    return confidence == VERIFIED
