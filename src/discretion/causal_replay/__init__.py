"""Causal setup replay over the FROZEN audited primitives.

This package consumes ONLY the audited ``discretion.primitive_reset``
structures (FVG / iFVG / rejection block). The superseded
``discretion.primitives`` FVG/iFVG/RB detectors are not imported here and take
no part in the replay -- old and new primitive IDs never mix (reset IDs are
``FVG2-`` / ``IFVG2-`` / ``RB2-``; the legacy prefixes never appear).

Integration method (disclosed): the frozen rejection block removed the old
``RB_CONFIRMED`` gate that the legacy branch-engine transition machine was
tuned on, so rather than rewire that tuned state machine to semantics it was
not built for, this is a fresh, self-contained, fully causal episode/branch
replay whose inputs are the audited structures. Every setup is constructed
strictly from information available at or before its trigger bar; no outcome
is computed or attached in the pre-outcome stage.
"""
