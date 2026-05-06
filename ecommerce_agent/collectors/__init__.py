"""开题报告数据收集：天气 API、CSV 导入、知识图谱三元组、联邦聚合包。

小红书/抖音/电商平台爬虫不在此实现；请使用平台官方导出或授权 API，再经 CSV/JSON 接入。
"""

from .csv_imports import (
    import_competitors_csv,
    import_openkg_style_triples_csv,
    import_shop_skus_csv,
    import_supply_chain_csv,
    import_tags_csv,
    import_trends_csv,
)
from .federated_package import package_for_federation
from .weather_open_meteo import collect_weather_bundle, summarize_season_signals

__all__ = [
    "collect_weather_bundle",
    "summarize_season_signals",
    "import_shop_skus_csv",
    "import_trends_csv",
    "import_competitors_csv",
    "import_supply_chain_csv",
    "import_openkg_style_triples_csv",
    "import_tags_csv",
    "package_for_federation",
]
