# PRIMITIVE_AUDIT_FAIL — SUPERSEDED

This atlas (and `../review_week_atlas_2025_07_14_18_repaired/`) was built on
the pre-reset primitive detectors (`discretion.primitives.fvg`,
`discretion.primitives.ifvg`, `discretion.primitives.rejection_block`).

Dylan's first manual primitive inspection found the rejection-block detector
encoded the wrong object, the FVG detector admitted gaps without useful size
stratification, and untouched-expiry was incorrectly labelled as FVG
continuation. Because candidates and branches downstream of those primitives
are built from an unverified vocabulary, this atlas's candidate universe and
adaptive evidence are **not** reused by the primitive reset
(`artifacts/primitive_reset_nqu6_2026_07_12_17/`).

Nothing here is deleted — it remains as provenance for why the reset was
required. See `artifacts/primitive_reset_nqu6_2026_07_12_17/` for the new,
narrow, timestamp-based primitive audit that supersedes this atlas's
primitive layer. Do not build new candidates/evidence on top of this atlas's
FVG/iFVG/RB objects.
