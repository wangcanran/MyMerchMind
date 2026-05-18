
import unittest
from ecommerce_agent.agents.dynamic_pricing_agent import DynamicPricingAgent

class TestDynamicPricingAgent(unittest.TestCase):

    def test_analyze_basic(self):
        agent = DynamicPricingAgent()
        product_info = {"id": "SKU001", "name": "Test Product"}
        competitor_prices = [100.0, 110.0, 105.0]
        store_cost_price = 80.0
        seasonal_factor = 1.0

        result = agent.analyze(
            product_info=product_info,
            competitor_prices=competitor_prices,
            store_cost_price=store_cost_price,
            seasonal_factor=seasonal_factor,
        )

        self.assertIn("recommendation", result)
        self.assertIn("suggested_price", result["recommendation"])
        self.assertGreater(result["recommendation"]["suggested_price"], store_cost_price)

if __name__ == '__main__':
    unittest.main()
