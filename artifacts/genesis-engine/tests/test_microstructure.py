import pytest
from decimal import Decimal
from src.microstructure.orderbook import UnifiedOrderBook, UnifiedBookLevel, MicrostructureEngine
from src.microstructure.slippage_model import SlippageModel
from src.microstructure.toxic_flow import ToxicFlowDetector


def test_unified_book_mid():
    book = UnifiedOrderBook(
        symbol="TEST",
        bids=[UnifiedBookLevel(Decimal("100"), Decimal("10"), "poly")],
        asks=[UnifiedBookLevel(Decimal("101"), Decimal("5"), "poly")],
    )
    assert book.mid() == Decimal("100.5")


def test_slippage_estimate():
    book = UnifiedOrderBook(
        symbol="TEST",
        bids=[UnifiedBookLevel(Decimal("100"), Decimal("1"), "poly")],
        asks=[UnifiedBookLevel(Decimal("101"), Decimal("1"), "poly")],
    )
    model = SlippageModel()
    est = model.estimate(book, "buy", Decimal("2"))
    assert est.filled_levels == 1
    assert est.slippage_bps > 0


def test_toxic_flow_detector():
    det = ToxicFlowDetector("BTCUSDT")
    for i in range(100):
        det.on_trade(65000.0 + i, 1.0, "buy" if i % 2 == 0 else "sell")
    sig = det.detect()
    assert 0 <= sig.toxicity_score <= 1.0
    assert sig.confidence > 0
