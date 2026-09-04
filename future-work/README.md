# Future Work — Not in the 12-Month MVP Scope

Per Design Doc Section 15/16, these are documented as future-work items
rather than shipped capabilities. Building them without the stated
prerequisite (clinical review, a real use case, etc.) would be "adding
something because it sounds impressive" — the design doc explicitly calls
that out as the wrong reason to build.

- **minor-symptom-guidance/** — Section 9.14. Architecture-only; no
  clinical content is included. Requires healthcare-professional review
  or a content partnership before any real symptom-guidance content ships.
- **offline-sync/** — Offline-first sync for low-connectivity areas.
- **patient-wellness-timeline/** — Optional mood-check + visual adherence
  record for the patient. Explicitly a stretch item, not core.

Also out of MVP scope per Section 9.14 (deliberately, not by oversight):
doctor dashboard with doctor login, drug-interaction simulation beyond the
curated demo dataset, full adherence analytics, emergency card,
computer-vision pill identification, automatic substitution, AI-generated
medical recommendations, hospital-system integration, multiple
caregiver-permission tiers, and MCP integration (only if a genuine
tool-calling use case emerges).
