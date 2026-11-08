"""The seed shapes (plan section 9). Titles and text are placeholders; DEF-01 stays deferred.

Ids are uuid5 over a fixed namespace and the slug, so they never change and reruns find the same
rows. Never change ``SEED_NAMESPACE`` or a slug: that would create duplicates in production.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

# Fixed forever. Generated once; do not edit.
SEED_NAMESPACE = uuid.UUID("6d8218b5-7a4f-4e6e-bfbc-c9a54d2ca581")

# Department slugs from migration 0002 (OPEN-26 D6).
ALL_DEPARTMENTS = ("human-resources", "finance", "engineering", "legal", "sales")


@dataclass(frozen=True)
class SeedDocument:
    slug: str
    title: str
    owner: str
    allowed: tuple[str, ...]
    pages: int
    paragraphs: tuple[str, ...]
    shape: str

    @property
    def filename(self) -> str:
        return f"{self.slug}.pdf"

    @property
    def document_id(self) -> uuid.UUID:
        return uuid.uuid5(SEED_NAMESPACE, f"document:{self.slug}")

    @property
    def revision_id(self) -> uuid.UUID:
        return uuid.uuid5(SEED_NAMESPACE, f"revision:{self.slug}")

    @property
    def storage_key(self) -> str:
        return f"documents/{self.document_id}/{self.revision_id}.pdf"


_NOTE = (
    "This is a fictional placeholder document for the KnowServe portfolio demo. "
    "It describes no real organization, policy or person."
)

SEED_DOCUMENTS: tuple[SeedDocument, ...] = (
    SeedDocument(
        slug="seed-company-handbook",
        title="Company Handbook (sample)",
        owner="human-resources",
        allowed=ALL_DEPARTMENTS,
        pages=3,
        shape="organization-wide",
        paragraphs=(
            _NOTE,
            "Welcome. This sample handbook is readable by every department and exists so that "
            "switching the active department keeps it in the library.",
            "Working hours. Core hours are placeholder values used to show page navigation.",
            "Expenses. Employees submit expenses through the fictional Expense Desk.",
            "Security. Report anything unusual to the fictional Security Desk.",
        ),
    ),
    SeedDocument(
        slug="seed-budget-planning",
        title="Budget Planning Guide (sample)",
        owner="finance",
        allowed=("finance", "engineering"),
        pages=2,
        shape="two-department",
        paragraphs=(
            _NOTE,
            "Owned by Finance and shared with Engineering. It shows a document that two "
            "departments can read while the other three cannot.",
            "Planning cycle. Teams submit placeholder estimates each quarter.",
        ),
    ),
    SeedDocument(
        slug="seed-contract-review-checklist",
        title="Contract Review Checklist (sample)",
        owner="legal",
        allowed=("sales",),
        pages=2,
        shape="owner-not-a-reader",
        paragraphs=(
            _NOTE,
            "Owned by Legal but readable only by Sales. Legal itself has no access row, which "
            "shows that the owner label grants nothing.",
            "Checklist. Confirm the fictional term, the fictional renewal and the fictional "
            "notice.",
        ),
    ),
    SeedDocument(
        slug="seed-incident-runbook",
        title="Incident Runbook (sample)",
        owner="engineering",
        allowed=("engineering",),
        pages=2,
        shape="single-department",
        paragraphs=(
            _NOTE,
            "Readable only by Engineering. Every other department gets the same neutral "
            "not-found answer for this document.",
            "Steps. Acknowledge the fictional alert, assess impact, and write a short summary.",
        ),
    ),
)
