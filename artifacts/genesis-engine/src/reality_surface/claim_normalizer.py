"""
reality_surface/claim_normalizer.py

Unifies probability estimates across tradable instruments:
  - Polymarket binary prices
  - Deribit option implied probabilities
  - Perpetual funding rates (sentiment proxy)
  - Insurance premiums (tail risk proxy)

Practical v6 — no metaverse, no quantum, just edge.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from collections import defaultdict
import numpy as np


@dataclass(frozen=True)
class ProbabilityClaim:
    """A normalized probability estimate from any source."""
    source: str           # "polymarket", "deribit", "funding", "insurance"
    event: str            # Normalized event key, e.g. "BTC>70000:2026-08-05"
    probability: float    # [0.01, 0.99]
    confidence: float     # [0, 1] based on liquidity / sample size
    timestamp: float      # Unix epoch
    latency_ms: float
    raw_data: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        assert 0.0 <= self.probability <= 1.0, f"Invalid probability: {self.probability}"
        assert 0.0 <= self.confidence <= 1.0, f"Invalid confidence: {self.confidence}"


@dataclass
class DivergenceSignal:
    """An actionable cross-venue mispricing."""
    event: str
    edge_bps: int                 # Edge in basis points
    direction: str                # e.g. "BUY_PM_SELL_DERIBIT"
    long_venue: str
    short_venue: str
    long_prob: float
    short_prob: float
    confidence: float
    expected_pnl: float
    hedge_ratio: float
    timestamp: float


class RealitySurface:
    """
    Live unified probability surface across all reality layers.

    Usage:
        surface = RealitySurface()
        surface.ingest_polymarket("BTC>70k", 0.62, liquidity_usd=150000)
        surface.ingest_deribit_option("BTC>70k", strike=70000, ...)

        consensus = surface.consensus_probability("BTC>70k")
        arb = surface.find_divergence("BTC>70k", threshold=0.025)
    """

    CLAIM_HALFLIFE: float = 300.0   # 5-minute half-life for claim decay
    MIN_CONFIDENCE: float = 0.15

    def __init__(self):
        self._claims: Dict[str, List[ProbabilityClaim]] = defaultdict(list)
        self._event_meta: Dict[str, dict] = {}
        self._divergence_history: List[DivergenceSignal] = []

    # ------------------------------------------------------------------
    # Ingestors
    # ------------------------------------------------------------------

    def ingest_polymarket(
        self,
        event: str,
        yes_price: float,
        liquidity_usd: float,
        spread: float = 0.02,
        raw: Optional[dict] = None,
    ) -> ProbabilityClaim:
        """Polymarket binary price IS the probability."""
        prob = float(np.clip(yes_price, 0.01, 0.99))
        liq_conf = min(1.0, liquidity_usd / 500_000)
        spread_penalty = max(0.0, 1.0 - spread * 10)
        confidence = liq_conf * spread_penalty

        claim = ProbabilityClaim(
            source="polymarket",
            event=event,
            probability=prob,
            confidence=confidence,
            timestamp=time.time(),
            latency_ms=50.0,
            raw_data=raw or {},
        )
        self._claims[event].append(claim)
        self._prune_old_claims(event)
        return claim

    def ingest_deribit_option(
        self,
        event: str,
        strike: float,
        spot: float,
        expiry_days: float,
        call_price: float,
        iv: float,
        raw: Optional[dict] = None,
    ) -> Optional[ProbabilityClaim]:
        """Convert short-dated option to implied binary probability via delta approximation."""
        if expiry_days <= 0:
            return None

        moneyness = spot / strike
        sigma = iv
        T = expiry_days / 365.0

        if T < 0.02:
            prob = 0.5 + (moneyness - 1.0) * 5.0
        else:
            d1 = (np.log(moneyness) + 0.5 * sigma ** 2 * T) / (sigma * np.sqrt(T))
            prob = 0.5 * (1 + np.tanh(d1 * np.sqrt(2 / np.pi)))

        prob = float(np.clip(prob, 0.01, 0.99))
        moneyness_penalty = 1.0 - abs(moneyness - 1.0)
        time_penalty = min(1.0, 7.0 / expiry_days) if expiry_days > 0 else 0
        confidence = moneyness_penalty * time_penalty * 0.7

        claim = ProbabilityClaim(
            source="deribit",
            event=event,
            probability=prob,
            confidence=confidence,
            timestamp=time.time(),
            latency_ms=20.0,
            raw_data=raw or {},
        )
        self._claims[event].append(claim)
        self._prune_old_claims(event)
        return claim

    def ingest_funding_rate(
        self,
        event: str,
        funding_8h: float,
        open_interest_usd: float,
        raw: Optional[dict] = None,
    ) -> ProbabilityClaim:
        """
        Funding rate proxies market sentiment.
        Positive funding = longs pay shorts = bullish.
        Mapped to probability via sigmoid.
        """
        funding_annual = funding_8h * 3 * 365
        prob = 1.0 / (1.0 + np.exp(-funding_annual * 2.0))
        prob = float(np.clip(prob, 0.01, 0.99))
        oi_conf = min(1.0, open_interest_usd / 1_000_000_000)
        confidence = oi_conf * 0.4   # Funding is noisy; cap confidence

        claim = ProbabilityClaim(
            source="funding",
            event=event,
            probability=prob,
            confidence=confidence,
            timestamp=time.time(),
            latency_ms=10.0,
            raw_data=raw or {},
        )
        self._claims[event].append(claim)
        self._prune_old_claims(event)
        return claim

    def ingest_insurance_premium(
        self,
        event: str,
        premium_annual: float,
        coverage_amount: float,
        raw: Optional[dict] = None,
    ) -> Optional[ProbabilityClaim]:
        """premium / coverage ≈ implied probability of event."""
        if coverage_amount <= 0:
            return None

        prob = float(np.clip(premium_annual / coverage_amount, 0.01, 0.99))

        claim = ProbabilityClaim(
            source="insurance",
            event=event,
            probability=prob,
            confidence=0.3,
            timestamp=time.time(),
            latency_ms=5000.0,
            raw_data=raw or {},
        )
        self._claims[event].append(claim)
        self._prune_old_claims(event)
        return claim

    # ------------------------------------------------------------------
    # Core Logic
    # ------------------------------------------------------------------

    def _prune_old_claims(self, event: str, max_age_sec: float = 600.0):
        cutoff = time.time() - max_age_sec
        self._claims[event] = [
            c for c in self._claims[event]
            if c.timestamp > cutoff and c.confidence >= self.MIN_CONFIDENCE
        ]

    def consensus_probability(self, event: str) -> Optional[float]:
        """Confidence-weighted, time-decayed consensus across all reality layers."""
        claims = self._claims.get(event, [])
        if not claims:
            return None

        now = time.time()
        weights, probs = [], []

        for c in claims:
            age = now - c.timestamp
            decay = 0.5 ** (age / self.CLAIM_HALFLIFE)
            w = c.confidence * decay
            weights.append(w)
            probs.append(c.probability)

        total_weight = sum(weights)
        if total_weight < 0.01:
            return None

        consensus = sum(p * w for p, w in zip(probs, weights)) / total_weight
        return float(np.clip(consensus, 0.01, 0.99))

    def consensus_uncertainty(self, event: str) -> Optional[float]:
        """Standard deviation of probability estimates — high = potential edge."""
        claims = self._claims.get(event, [])
        if len(claims) < 2:
            return None
        return float(np.std([c.probability for c in claims]))

    def find_divergence(
        self,
        event: str,
        threshold: float = 0.025,
        min_confidence: float = 0.3,
    ) -> Optional[DivergenceSignal]:
        """
        Find actionable mispricings between two high-confidence sources.
        Returns DivergenceSignal if probability gap > threshold AND
        both sources have confidence >= min_confidence.
        """
        claims = self._claims.get(event, [])
        if len(claims) < 2:
            return None

        now = time.time()
        recent = [
            c for c in claims
            if c.confidence >= min_confidence and (now - c.timestamp) < 300
        ]

        if len(recent) < 2:
            return None

        best, best_gap = None, 0.0

        for i, c1 in enumerate(recent):
            for c2 in recent[i + 1:]:
                if c1.source == c2.source:
                    continue
                gap = abs(c1.probability - c2.probability)
                if gap > best_gap and gap >= threshold:
                    best_gap = gap
                    best = (c1, c2)

        if best is None:
            return None

        c1, c2 = best
        long_claim, short_claim = (c1, c2) if c1.probability < c2.probability else (c2, c1)

        signal = DivergenceSignal(
            event=event,
            edge_bps=int(best_gap * 10_000),
            direction=f"BUY_{long_claim.source.upper()}_SELL_{short_claim.source.upper()}",
            long_venue=long_claim.source,
            short_venue=short_claim.source,
            long_prob=long_claim.probability,
            short_prob=short_claim.probability,
            confidence=min(long_claim.confidence, short_claim.confidence),
            expected_pnl=best_gap * 1000 * min(long_claim.confidence, short_claim.confidence),
            hedge_ratio=1.0,
            timestamp=time.time(),
        )

        self._divergence_history.append(signal)
        if len(self._divergence_history) > 10_000:
            self._divergence_history = self._divergence_history[-10_000:]

        return signal

    def get_all_events(self) -> List[str]:
        return list(self._claims.keys())

    def get_event_snapshot(self, event: str) -> dict:
        claims = self._claims.get(event, [])
        return {
            "event": event,
            "n_claims": len(claims),
            "consensus_prob": self.consensus_probability(event),
            "uncertainty": self.consensus_uncertainty(event),
            "sources": list(set(c.source for c in claims)),
            "latest_claims": [
                {
                    "source": c.source,
                    "prob": c.probability,
                    "conf": c.confidence,
                    "age_sec": round(time.time() - c.timestamp, 1),
                }
                for c in sorted(claims, key=lambda x: x.timestamp, reverse=True)[:5]
            ],
        }
