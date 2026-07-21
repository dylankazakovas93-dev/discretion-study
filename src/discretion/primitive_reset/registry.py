"""Dedicated id registry for the primitive-reset detectors.

Deliberately separate from ``discretion.primitives.base.IdRegistry`` --
reset IDs (``FVG2-``, ``IFVG2-``, ``RB2-``) must never be mixed with the
superseded ``FVG-``/``IFVG-``/``RB-`` sequences from the old detectors.
"""

from __future__ import annotations


class ResetRegistry:
    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self.fvgs: dict[str, object] = {}
        self.ifvgs: dict[str, object] = {}
        self.rbs: dict[str, object] = {}

    def new_id(self, prefix: str) -> str:
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}-{n:06d}"

    def register_fvg(self, rec) -> None:
        self.fvgs[rec.id] = rec

    def register_ifvg(self, rec) -> None:
        self.ifvgs[rec.id] = rec

    def register_rb(self, rec) -> None:
        self.rbs[rec.id] = rec
