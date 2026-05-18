"""python -m ecommerce_agent.collectors …"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .csv_imports import (
    import_competitors_csv,
    import_openkg_style_triples_csv,
    import_shop_skus_csv,
    import_supply_chain_csv,
    import_tags_csv,
    import_trends_csv,
)
from .federated_package import package_for_federation
from .paths import collected_dir
from .weather_open_meteo import collect_weather_bundle, summarize_season_signals


def _cmd_weather(args: argparse.Namespace) -> int:
    out = collect_weather_bundle(
        args.lat,
        args.lon,
        history_days=args.days,
        city_label=args.city or "",
        out_path=Path(args.output) if args.output else None,
    )
    bundle = json.loads(out.read_text(encoding="utf-8"))
    summary = summarize_season_signals(bundle)
    print(f"已写入：{out}")
    print(f"季节摘要：{json.dumps(summary, ensure_ascii=False)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="服装电商智能体 — 数据收集（合规来源）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_w = sub.add_parser("weather", help="Open-Meteo 历史天气 + 预报（可选 OpenWeather 当前天气）")
    p_w.add_argument("--lat", type=float, default=31.23, help="纬度（默认：上海附近）")
    p_w.add_argument("--lon", type=float, default=121.47, help="经度")
    p_w.add_argument("--days", type=int, default=365, help="历史天数（归档 API）")
    p_w.add_argument("--city", default="", help="备注城市名（仅写入 JSON，不参与请求）")
    p_w.add_argument("--output", default="", help="输出路径，默认 data/collected/weather_bundle.json")
    p_w.set_defaults(func=_cmd_weather)

    def csv_cmd(name: str, fn, help_txt: str) -> None:
        p = sub.add_parser(name, help=help_txt)
        p.add_argument("input_csv", type=Path, help="输入 CSV 路径")
        p.add_argument(
            "-o",
            "--output",
            type=Path,
            default=None,
            help="输出 JSON（默认写入 data/collected/）",
        )
        p.set_defaults(_csv_fn=fn)

    csv_cmd(
        "shop-csv",
        import_shop_skus_csv,
        "本店经营数据：平台导出 CSV → erp_skus 兼容 JSON",
    )
    csv_cmd(
        "trends-csv",
        import_trends_csv,
        "社媒趋势：榜单/整理 CSV → trends JSON",
    )
    csv_cmd(
        "competitors-csv",
        import_competitors_csv,
        "竞品对照 CSV → competitors JSON",
    )
    csv_cmd(
        "supply-csv",
        import_supply_chain_csv,
        "供应链 CSV → supply_chain.json",
    )
    csv_cmd(
        "triples-csv",
        import_openkg_style_triples_csv,
        "知识图谱三元组 CSV → triples JSON",
    )
    csv_cmd(
        "tags-csv",
        import_tags_csv,
        "商品标签 CSV → tags JSON",
    )

    p_f = sub.add_parser("federate", help="竞品 JSON → 联邦学习用脱敏聚合包（非 FATE 运行时）")
    p_f.add_argument("competitors_json", type=Path, help="competitors JSON 路径")
    p_f.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="默认 data/collected/federation_aggregate.json",
    )

    def _run_federate(args: argparse.Namespace) -> int:
        out = args.output or (collected_dir() / "federation_aggregate.json")
        package_for_federation(args.competitors_json, out)
        print(f"已写入：{out}")
        return 0

    p_f.set_defaults(func=_run_federate)

    args = parser.parse_args()

    if args.cmd == "weather":
        return args.func(args)

    if args.cmd == "federate":
        return _run_federate(args)

    if args.cmd in (
        "shop-csv",
        "trends-csv",
        "competitors-csv",
        "supply-csv",
        "triples-csv",
        "tags-csv",
    ):
        fn = args._csv_fn
        out = args.output
        if out is None:
            default_names = {
                "shop-csv": "erp_skus_collected.json",
                "trends-csv": "trends_collected.json",
                "competitors-csv": "competitors_collected.json",
                "supply-csv": "supply_chain_collected.json",
                "triples-csv": "triples_collected.json",
                "tags-csv": "tags_collected.json",
            }
            out = collected_dir() / default_names[args.cmd]
        path = fn(args.input_csv, out)
        print(f"已写入：{path}")
        return 0

    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
