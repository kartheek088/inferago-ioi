"""Inferago Tech Services — the REAL business profile used by eligibility and scoring.

Do not add services, revenue, certifications, staff, projects or references here unless they
are real and approved by the owner. `None` means "not established" and is never treated as
satisfying a requirement.
"""

from typing import Any

from pydantic import BaseModel


class BusinessProfile(BaseModel):
    company_name: str = "Inferago Tech Services"
    legal_structure: str = "sole_proprietorship"
    country: str = "India"
    region: str = "Tamil Nadu"
    udyam_msme_registered: bool = True
    pan_available: bool = True  # proprietor-linked PAN
    pan_note: str = "PAN is proprietor-linked (sole proprietorship)."
    aadhaar_available: bool = True
    gst_registered: bool = False
    corporate_project_credentials: bool = False
    completed_projects_documented: int = 0
    similar_work_certificates: bool = False
    annual_turnover_inr: float | None = None  # not established
    dedicated_employees: int = 0
    team_note: str = "Founder with informal contributors; no dedicated TS employees."
    technical_certifications: list[str] = []
    security_certifications: list[str] = []
    insurance: list[str] = []
    digital_signature_certificate: bool | None = None  # not recorded
    international_delivery_desired: bool = True
    services: list[str] = [
        "Backend and software development",
        "API development and integration",
        "Workflow automation",
        "Internal business applications",
        "Software integration and process digitisation",
    ]


SERVICE_KEYS = {
    "backend": "Backend and software development",
    "api": "API development and integration",
    "automation": "Workflow automation",
    "internal_apps": "Internal business applications",
    "integration": "Software integration and process digitisation",
}

DEFAULT_PROFILE = BusinessProfile()


def load_profile(overrides: dict[str, Any] | None = None) -> BusinessProfile:
    """Return the profile, applying owner-edited overrides stored in app settings.

    Services cannot be added through overrides (approval required in code review).
    """
    data = DEFAULT_PROFILE.model_dump()
    if overrides:
        for key, value in overrides.items():
            if key in data and key != "services":
                data[key] = value
    return BusinessProfile(**data)
