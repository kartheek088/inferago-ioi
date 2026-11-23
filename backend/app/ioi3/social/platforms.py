"""Recognising public social-commerce profile links, and what may legitimately be read from them.

Only the public profile page of a *business* account is ever fetched, and only when the platform
serves it without a login. Nothing here opens a DM, a chat, a follower list or a private profile.

WhatsApp is a messaging product, not a directory: a `wa.me` link is a contact route the seller
published, never a discoverable listing and never permission to send bulk messages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

INSTAGRAM = "instagram"
FACEBOOK = "facebook"
WHATSAPP = "whatsapp"
OTHER = "other"
PLATFORMS = (INSTAGRAM, FACEBOOK, WHATSAPP, OTHER)

PLATFORM_LABEL = {INSTAGRAM: "Instagram", FACEBOOK: "Facebook", WHATSAPP: "WhatsApp Business",
                  OTHER: "Other public storefront"}

# Instagram and Facebook serve most profile pages only to signed-in clients and their robots.txt
# restricts automated access, so IOI does not fetch them. The owner opens the profile themselves.
FETCHABLE = {INSTAGRAM: False, FACEBOOK: False, WHATSAPP: False, OTHER: True}

_IG_HOSTS = ("instagram.com", "www.instagram.com", "instagr.am")
_FB_HOSTS = ("facebook.com", "www.facebook.com", "m.facebook.com", "fb.com", "fb.me", "web.facebook.com")
_WA_HOSTS = ("wa.me", "api.whatsapp.com", "web.whatsapp.com", "chat.whatsapp.com", "whatsapp.com", "www.whatsapp.com")

# Reserved Instagram/Facebook paths that are never a business profile.
_RESERVED = {"p", "reel", "reels", "explore", "stories", "direct", "accounts", "about", "developers", "help",
             "privacy", "terms", "legal", "sharer", "pages", "groups", "events", "marketplace", "watch",
             "login", "signup", "business", "profile.php", "permalink.php", "story.php", "photo.php"}

_HANDLE_RX = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._-]{0,78}[A-Za-z0-9._]$|^[A-Za-z0-9._]$")
_IN_PHONE_RX = re.compile(r"^(?:91)?([6-9]\d{9})$")


@dataclass(frozen=True)
class ProfileRef:
    """A recognised public account reference."""

    platform: str
    handle: str
    url: str  # canonical public URL
    kind: str = "unknown"  # business | creator | page | personal | unknown
    note: str | None = None

    @property
    def label(self) -> str:
        return PLATFORM_LABEL.get(self.platform, self.platform)


class NotAProfile(ValueError):
    """The link is not a public business profile IOI can use."""


def normalise_phone(raw: str) -> str | None:
    """An Indian mobile number as 10 digits, or None. WhatsApp Business needs a mobile."""
    digits = re.sub(r"\D", "", raw or "")
    digits = digits.removeprefix("0")
    m = _IN_PHONE_RX.match(digits[-12:] if len(digits) > 10 else digits)
    return m.group(1) if m else None


def parse(url_or_handle: str) -> ProfileRef:
    """Recognise a pasted public profile link, @handle or WhatsApp number.

    Raises NotAProfile with a plain-language reason when the input is not usable.
    """
    raw = (url_or_handle or "").strip()
    if not raw:
        raise NotAProfile("Paste a public profile link, an @handle or a WhatsApp business number.")

    # A WhatsApp number typed on its own.
    if re.fullmatch(r"[\d\s+()-]{10,18}", raw):
        phone = normalise_phone(raw)
        if phone:
            return ProfileRef(WHATSAPP, phone, f"https://wa.me/91{phone}", kind="business",
                              note="A published WhatsApp number is a contact route, not proof of a business.")
        raise NotAProfile(f"'{raw}' is not a valid Indian mobile number.")

    # Bare @handle or a plain handle: assume Instagram, the dominant social-commerce platform here.
    if raw.startswith("@") or re.fullmatch(r"[A-Za-z0-9_]{2,30}", raw):
        handle = raw.lstrip("@").strip()
        if not _HANDLE_RX.match(handle):
            raise NotAProfile(f"'{raw}' is not a valid handle.")
        return ProfileRef(INSTAGRAM, handle.lower(), f"https://www.instagram.com/{handle.lower()}/",
                          note="Assumed Instagram from the handle — check it is the right account.")

    if not re.match(r"^https?://", raw):
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if not host:
        raise NotAProfile("That link has no website address in it.")
    segs = [s for s in parts.path.split("/") if s]

    if host in _IG_HOSTS:
        if not segs or segs[0].lower() in _RESERVED:
            raise NotAProfile("That Instagram link points to a post or a section, not a business profile. "
                              "Use the profile link, e.g. https://www.instagram.com/theirhandle/")
        handle = segs[0].lstrip("@").lower()
        if not _HANDLE_RX.match(handle):
            raise NotAProfile(f"'{segs[0]}' is not a valid Instagram handle.")
        return ProfileRef(INSTAGRAM, handle, f"https://www.instagram.com/{handle}/")

    if host in _FB_HOSTS:
        if segs and segs[0].lower() == "p" and len(segs) > 1:  # /p/Page-Name-123456
            return ProfileRef(FACEBOOK, segs[1].lower(), f"https://www.facebook.com/p/{segs[1]}", kind="page")
        if not segs or segs[0].lower() in _RESERVED:
            ident = parse_qs(parts.query).get("id", [""])[0]
            if ident.isdigit():
                return ProfileRef(FACEBOOK, ident, f"https://www.facebook.com/profile.php?id={ident}", kind="page")
            raise NotAProfile("That Facebook link points to a post or a section, not a business page. "
                              "Use the page link, e.g. https://www.facebook.com/theirpage")
        handle = segs[0].lower()
        if not _HANDLE_RX.match(handle):
            raise NotAProfile(f"'{segs[0]}' is not a valid Facebook page name.")
        return ProfileRef(FACEBOOK, handle, f"https://www.facebook.com/{handle}", kind="page")

    if host in _WA_HOSTS:
        if "chat.whatsapp.com" in host:
            raise NotAProfile("That is a WhatsApp group invite. IOI never joins groups or reads group members.")
        cand = (segs[0] if segs else "") or parse_qs(parts.query).get("phone", [""])[0]
        phone = normalise_phone(cand)
        if not phone:
            raise NotAProfile("That WhatsApp link has no Indian mobile number in it.")
        return ProfileRef(WHATSAPP, phone, f"https://wa.me/91{phone}", kind="business",
                          note="A published WhatsApp number is a contact route, not proof of a business.")

    if host.endswith(("linkedin.com", "justdial.com", "indiamart.com", "twitter.com", "x.com")):
        raise NotAProfile(f"IOI does not read {host} automatically. "
                          "Add the seller's own profile, catalogue or website link instead.")

    # Any other public link: the seller's own site, a catalogue page, a market/exhibitor listing.
    return ProfileRef(OTHER, (host.removeprefix("www.") + parts.path)[:120], raw, kind="unknown")


def is_social_link(url: str | None) -> bool:
    if not url:
        return False
    host = (urlsplit(url if re.match(r"^https?://", url) else "https://" + url).hostname or "").lower()
    return host in _IG_HOSTS + _FB_HOSTS + _WA_HOSTS


def catalogue_hint(url: str | None) -> bool:
    """A published catalogue / order-form link (a sign that orders arrive outside a real system)."""
    if not url:
        return False
    u = url.lower()
    return any(k in u for k in ("linktr.ee", "wa.me", "/catalogue", "/catalog", "bit.ly", "forms.gle",
                                "docs.google.com/forms", "instamojo", "razorpay.me", "/shop", "dukaan",
                                "mystore", "shopify", "wa.link"))
