"""
Den Danske Metode test-suite — kør med:  python -m unittest discover -s tests

Dækker den kritiske matematik (Kelly, allokering), atomisk persistens, og auto-
traderens køb→trailing-stop-livscyklus i tør-kørsel (uden netværk, via mocks).
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine import kelly, allocator, store, autotrader, exchange


class TestKelly(unittest.TestCase):
    def test_no_edge_means_no_bet(self):
        # p = markedets implicitte sandsynlighed -> præcis nul edge -> intet bud
        self.assertEqual(kelly.binary_kelly(0.50, 2.0), 0.0)

    def test_positive_edge_is_fractional(self):
        # Fuld Kelly = 0.10 ved p=0.55/odds=2.0; 1/4 Kelly = 0.025
        self.assertAlmostEqual(kelly.binary_kelly(0.55, 2.0), 0.025, places=4)

    def test_position_is_capped(self):
        # Enormt edge må aldrig overstige MAX_POSITION_FRACTION
        self.assertLessEqual(kelly.binary_kelly(0.99, 10.0), kelly.MAX_POSITION_FRACTION)

    def test_continuous_kelly_negative_return_zero(self):
        self.assertEqual(kelly.continuous_kelly(-0.02, 0.10), 0.0)

    def test_remove_vig_sums_to_one(self):
        probs = kelly.remove_vig([2.10, 3.40, 3.60])
        self.assertAlmostEqual(sum(probs), 1.0, places=9)


class TestAllocator(unittest.TestCase):
    def test_empty_when_no_opportunities(self):
        self.assertEqual(allocator.allocate(200, []), [])

    def test_respects_cash_buffer(self):
        # Mange stærke muligheder -> samlet indsats må ikke røre kontant-bufferen
        opps = [{"type": "market", "id": f"A{i}", "name": f"A{i}", "price": 100,
                 "expected_return": 0.05, "volatility": 0.08} for i in range(8)]
        actions = allocator.allocate(200, opps)
        deployed = sum(a["stake_dkk"] for a in actions)
        self.assertLessEqual(deployed, 200 * (1 - allocator.CASH_BUFFER) + 0.01)

    def test_skips_below_min_stake(self):
        for a in allocator.allocate(200, [{"type": "market", "id": "X", "name": "X",
                "price": 100, "expected_return": 0.05, "volatility": 0.08}]):
            self.assertGreaterEqual(a["stake_dkk"], allocator.MIN_STAKE)


class TestStore(unittest.TestCase):
    def test_atomic_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.json")
            self.assertIsNone(store.load(path))
            store.save(path, {"a": 1, "æ": "ø"})
            self.assertEqual(store.load(path), {"a": 1, "æ": "ø"})
            # ingen efterladt temp-fil
            self.assertFalse(os.path.exists(path + ".tmp"))


class TestAutotraderDryRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_path = autotrader.STATE_PATH
        autotrader.STATE_PATH = os.path.join(self._tmp.name, "live_state.json")
        # mock børsen: ét signal, fast pris, ingen live-handel, intet netværk
        self._orig = (exchange.live_enabled, exchange.fetch_signals, exchange.get_price)
        exchange.live_enabled = lambda: False
        exchange.fetch_signals = lambda: [{
            "type": "market", "id": "BTC/EUR", "name": "BTC/EUR", "price": 100.0,
            "expected_return": 0.05, "volatility": 0.10, "reason": "test"}]
        self._price = [100.0]
        exchange.get_price = lambda s: self._price[0]
        autotrader.reset(200)

    def tearDown(self):
        autotrader.STATE_PATH = self._orig_path
        exchange.live_enabled, exchange.fetch_signals, exchange.get_price = self._orig
        self._tmp.cleanup()

    def test_buys_then_trailing_stop_protects_profit(self):
        r1 = autotrader.run_cycle()
        self.assertFalse(r1["live"])
        self.assertEqual(len(autotrader.status()["positions"]), 1)

        self._price[0] = 120.0  # ny top, trailing stop armes
        autotrader.run_cycle()
        self.assertEqual(len(autotrader.status()["positions"]), 1)

        self._price[0] = 104.0  # >12% under toppen -> trailing stop
        autotrader.run_cycle()
        hist = autotrader.status()["history"]
        self.assertTrue(any("trailing-stop" in h["reason"] for h in hist))
        self.assertTrue(any(h["pnl"] > 0 for h in hist))

    def test_kill_switch_closes_all(self):
        autotrader.run_cycle()
        autotrader.flatten()
        self.assertEqual(len(autotrader.status()["positions"]), 0)


if __name__ == "__main__":
    unittest.main()
