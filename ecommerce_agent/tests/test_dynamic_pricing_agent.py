
import unittest
from ecommerce_agent.agents.dynamic_pricing_agent import DynamicPricingAgent

class TestDynamicPricingAgent(unittest.TestCase):

    def test_analyze_basic(self):
        agent = DynamicPricingAgent()
        competitor_prices = [100.0, 110.0, 105.0]
        store_cost_price = 80.0
        seasonal_factor = 1.0

        result = agent.analyze(
            product_info={"sku_id": "SKU001", "name": "Test Product", "price": 120.0},
            competitor_prices=competitor_prices,
            store_cost_price=store_cost_price,
            seasonal_factor=seasonal_factor,
        )

        self.assertIn("suggested_price", result)
        self.assertGreater(result["suggested_price"], store_cost_price)

    def test_market_intel_implied_cost_ceiling_respects_target_margin(self):
        agent = DynamicPricingAgent()
        competitor_prices = [100.0, 110.0, 105.0]
        r = agent.analyze(
            product_info={"sku_id": "SKU002", "name": "Intel", "price": 0.0},
            competitor_prices=competitor_prices,
            store_cost_price=0.0,
            pricing_mode="market_intel",
            target_gross_margin=40,
        )
        mi = r.get("market_intel") or {}
        self.assertEqual(mi.get("assumed_target_gross_margin"), 0.4)
        sweet = float(mi.get("sweet_spot") or 0)
        self.assertEqual(mi.get("implied_cost_ceiling"), max(1, int(round(sweet * 0.6))))

    def test_market_intel_sweet_below_p25_sets_tension_note(self) -> None:
        agent = DynamicPricingAgent()
        prices = [float(x) for x in range(100, 190, 2)]
        products = [{"price": p, "sales": "2"} for p in prices]
        for p in (52, 53, 54, 55, 56):
            products.append({"price": float(p), "sales": "9000人付款"})
        r = agent.analyze(
            product_info={"sku_id": "NP1", "name": "测款", "price": 0.0},
            competitor_prices=prices + [52, 53, 54, 55, 56],
            store_cost_price=0.0,
            pricing_mode="market_intel",
            competitor_products=products,
        )
        mi = r.get("market_intel") or {}
        self.assertEqual(mi.get("anchor_band_tension"), "sweet_below_p25")
        self.assertIn("P25", str(mi.get("sweet_vs_band_note") or ""))


if __name__ == '__main__':
    unittest.main()
