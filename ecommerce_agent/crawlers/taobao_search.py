"""
淘宝搜索抓取模块。

核心能力：
- 输入关键词，返回商品信息列表（不落盘）
- 批量搜索多个关键词（复用浏览器实例）
- 销量文案规范化

对外接口：
- search_taobao_products(keyword, ...) -> List[ProductItem]
- search_batch(keywords, ...) -> Dict[str, List[ProductItem]]
- normalize_sales(text) -> Optional[int]
- ProductItem: TypedDict with title / price / sales / shop / url

注意：`sales` 直接使用搜索页文案，可能是「xxx 人付款」「已售 xxx」等形式。
可用 normalize_sales() 转为整数。搜索页无法获取销量的商品（如仅显示"看过"），
建议调用方直接跳过不参考。
"""

from __future__ import annotations

import os
import json
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, TypedDict
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

try:
    from DrissionPage import ChromiumPage
except ImportError:  # pragma: no cover - 仅在未安装浏览器依赖时触发
    ChromiumPage = None


_DEFAULT_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

_LOGIN_URL_HINTS = ("login.taobao.com", "passport.taobao.com", "login")
_LOGIN_TEXT_HINTS = ("登录", "扫码登录", "账号登录", "请先登录")


def _load_repo_dotenv() -> None:
    """加载仓库根目录 .env（不覆盖系统/进程已有变量）。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    repo_root = Path(__file__).resolve().parents[2]
    env_path = repo_root / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


_load_repo_dotenv()


def _debug_enabled() -> bool:
    """是否开启调试日志（TAOBAO_DEBUG=1/true/on）。"""
    return os.getenv("TAOBAO_DEBUG", "").strip().lower() in {"1", "true", "on", "yes"}


def _debug_log(message: str) -> None:
    """按需输出调试日志。"""
    if _debug_enabled():
        print(f"[taobao-debug] {message}")


class ProductItem(TypedDict, total=False):
    """搜索结果商品条目。"""

    title: str
    price: str
    sales: str
    shop: str
    url: str


def normalize_sales(text: str) -> Optional[int]:
    """将销量文案规范化为整数。

    支持格式：
    - "已售1234" / "已售 1234件" -> 1234
    - "已售1.2万+" -> 12000
    - "356人付款" -> 356
    - "月销500+" -> 500

    不识别的格式（如"xx人看过"）返回 None，因为浏览量≠销量。
    """
    if not text or not isinstance(text, str):
        return None
    text = text.strip()

    # 排除"看过"——这是浏览量，不是销量
    if "看过" in text:
        return None

    # 匹配"已售xxx" / "xxx人付款" / "付款 xxx" / "月销xxx"
    # 注意：淘宝常见 "7000+" 格式，+ 号需要兼容
    m = re.search(r"(?:已售|月销)\s*([0-9]+(?:\.[0-9]+)?)\s*(万?\+?)?", text)
    if not m:
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(万?\+?)?\s*人付款", text)
    if not m:
        m = re.search(r"付款\s*([0-9]+(?:\.[0-9]+)?)\s*(万?\+?)?", text)
    if not m:
        # 纯数字兜底（如接口直接返回数值字符串）
        m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(万?\+?)?", text)
    if not m:
        return None

    num_str = m.group(1)
    unit = m.group(2) or ""

    try:
        value = float(num_str)
    except ValueError:
        return None

    if "万" in unit:
        value *= 10000

    return int(value)


def _parse_cookie_string(cookie_string: str) -> Dict[str, str]:
    """将 'k1=v1; k2=v2' 格式的 Cookie 字符串解析为字典。"""
    cookies: Dict[str, str] = {}
    raw = (cookie_string or "").strip()
    if not raw:
        return cookies

    for part in raw.split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name:
            cookies[name] = value
    return cookies


def _inject_cookies_to_page(page: "ChromiumPage", cookie_string: str) -> None:
    """向浏览器页面注入 Cookie，失败时静默跳过。

    同时写入 .taobao.com / .tmall.com 两个域，避免后续访问 Tmall 链接时
    丢失登录态。
    """
    cookies = _parse_cookie_string(cookie_string)
    if not cookies:
        return
    domains = (".taobao.com", ".tmall.com")
    for name, value in cookies.items():
        for domain in domains:
            try:
                page.set.cookies(
                    {
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": "/",
                    }
                )
            except Exception:
                continue


def _first_non_empty_text(node: Tag, selectors: List[str]) -> str:
    """按优先级从节点中提取第一个非空文本。"""
    for selector in selectors:
        target = node.select_one(selector)
        if target:
            text = target.get_text(strip=True)
            if text:
                return text
    return ""


def _extract_from_html(html: str, max_items: Optional[int] = None) -> List[ProductItem]:
    """从 HTML 中提取商品列表。"""
    soup = BeautifulSoup(html, "html.parser")

    item_selectors = [
        # 新版列表页（商品卡片根节点是 a）
        "div.PageContent--contentWrap--mep7AEm > div.LeftLay--leftWrap--xBQipVc > "
        "div.LeftLay--leftContent--AMmPNfB > div.Content--content--sgSCZ12 > div > a",
        # 兼容老结构
        ".item.J_MouserOnverReq",
        ".item",
        ".J_MouserOnverReq",
        "[data-nid]",
        ".Content--contentInner--QVTcU0M",
    ]
    items: List[Tag] = []
    for selector in item_selectors:
        items = soup.select(selector)
        if items:
            break

    results: List[ProductItem] = []
    for item in items:
        product: ProductItem = {
            "title": _first_non_empty_text(
                item,
                [
                    ".title a",
                    ".title",
                    ".Title--title--jCOPvpf",
                    ".Title--titleText--qG2wAjA",
                ],
            ),
            "price": _first_non_empty_text(
                item,
                [
                    ".price .g_price-highlight",
                    ".price strong",
                    ".price",
                    ".Price--priceInt--ZlsSi_M",
                    ".Price--priceText--V8_y_b5",
                ],
            ),
            "sales": _first_non_empty_text(
                item,
                [
                    ".deal-cnt",
                    ".deal-cnt a",
                    ".Price--realSales--FhTZc7U",
                    ".RealSales--realSales--Xd_icyP",
                ],
            ),
            "shop": _first_non_empty_text(
                item,
                [
                    ".shopname",
                    ".shop a",
                    ".ShopInfo--shopName--rg6mGmy",
                    ".ShopInfo__shopName",
                ],
            ),
        }

        if not any(product.values()):
            continue

        results.append(product)
        if max_items is not None and max_items > 0 and len(results) >= max_items:
            break

    return results


def _iter_dict_nodes(obj: Any) -> Iterable[Dict[str, Any]]:
    """递归遍历任意 JSON 结构中的 dict 节点。"""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dict_nodes(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dict_nodes(item)


def _as_text(value: Any) -> str:
    """将任意值尽量转成可读文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("text", "value", "content", "name", "title"):
            nested = value.get(key)
            if nested:
                return _as_text(nested)
    return ""


def _find_sold_text_in_obj(obj: Any) -> str:
    """
    递归查找对象中的"已售"文案。

    例如：已售123、已售 1.2万+
    """
    if isinstance(obj, str):
        m = re.search(r"已售\s*([0-9]+(?:\.[0-9]+)?(?:万\+?)?)", obj)
        if m:
            return f"已售{m.group(1)}"
        return ""
    if isinstance(obj, dict):
        for key in (
            "sellCount",
            "soldQuantity",
            "soldText",
            "saleText",
            "tradeDesc",
            "salesDesc",
        ):
            if key in obj:
                val = _as_text(obj.get(key))
                if val:
                    if "已售" in val:
                        return val
                    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?(?:万\+?)?", val):
                        return f"已售{val}"
        for value in obj.values():
            found = _find_sold_text_in_obj(value)
            if found:
                return found
        return ""
    if isinstance(obj, list):
        for item in obj:
            found = _find_sold_text_in_obj(item)
            if found:
                return found
        return ""
    return ""


def _extract_products_from_payload(
    payload: Any,
    max_items: Optional[int] = None,
) -> List[ProductItem]:
    """
    从接口 JSON 响应中提取商品列表（通用键名兼容）。

    仅采集 title / price / sales / shop 四个对外字段。
    """
    results: List[ProductItem] = []
    seen: set[tuple[str, str]] = set()

    title_keys = ("title", "raw_title", "name", "itemTitle", "auctionTitle")
    price_keys = ("price", "view_price", "salePrice", "priceText", "priceShow")
    sales_keys = ("sales", "sold", "dealCnt", "sellCount", "realSales")
    shop_keys = ("shop", "shopName", "nick", "sellerNick", "seller", "shop_name")
    id_keys = ("nid", "itemId", "item_id", "auctionId", "id")

    for node in _iter_dict_nodes(payload):
        title = ""
        price = ""
        shop = ""
        item_id = ""

        for key in title_keys:
            title = _as_text(node.get(key))
            if title:
                break
        for key in price_keys:
            price = _as_text(node.get(key))
            if price:
                break
        # 优先找"已售"语义字段，避免拿到"xx人看过"
        sales = _find_sold_text_in_obj(node)
        if not sales:
            for key in sales_keys:
                sales = _as_text(node.get(key))
                if sales:
                    break
        for key in shop_keys:
            shop = _as_text(node.get(key))
            if shop:
                break
        for key in id_keys:
            item_id = _as_text(node.get(key))
            if item_id and item_id.isdigit():
                break
            item_id = ""

        if title:
            title = re.sub(r"<[^>]+>", "", title).strip()
        if not title or (not price and not shop):
            continue

        dedup_key = (title, shop)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        product: ProductItem = {
            "title": title,
            "price": price,
            "sales": sales,
            "shop": shop,
        }
        if item_id:
            product["url"] = f"https://item.taobao.com/item.htm?id={item_id}"

        results.append(product)
        if max_items is not None and max_items > 0 and len(results) >= max_items:
            break
    return results


def _coerce_payload_to_json(payload: Any) -> Any:
    """
    将接口返回体标准化为 JSON 对象。

    兼容：
    - dict/list 直接返回
    - mtopjsonp123({...}) 这类 JSONP 字符串
    """
    if isinstance(payload, (dict, list)):
        return payload
    if not isinstance(payload, str):
        return None

    text = payload.strip()
    if not text:
        return None
    if text.startswith("{") and text.endswith("}"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    m = re.match(r"^[A-Za-z0-9_]+\((.*)\)\s*;?\s*$", text, re.S)
    if not m:
        return None
    inner = m.group(1).strip()
    try:
        return json.loads(inner)
    except json.JSONDecodeError:
        return None


def _fetch_products_by_browser_api(
    keyword: str,
    cookie_string: str = "",
    max_items: Optional[int] = None,
    wait_seconds: int = 2,
    listen_rounds: int = 15,
    page: Optional["ChromiumPage"] = None,
) -> List[ProductItem]:
    """
    直接访问搜索页并监听前端接口，提取商品数据。
    """
    if ChromiumPage is None:
        return []

    url = f"https://s.taobao.com/search?q={quote(keyword)}"
    own_page = page is None
    if own_page:
        page = ChromiumPage()
        page.get("https://www.taobao.com/")
        page.wait(1)
        _inject_cookies_to_page(page, cookie_string)

    try:
        page.listen.start("h5api.m.taobao.com")
        page.get(url)
        page.wait(wait_seconds)

        merged: List[ProductItem] = []
        seen: set[tuple[str, str]] = set()

        for idx in range(max(listen_rounds, 1)):
            if max_items is not None and max_items > 0 and len(merged) >= max_items:
                break

            resp = page.listen.wait(timeout=2)
            if not resp:
                page.scroll.to_bottom()
                page.wait(1)
                continue

            body = getattr(resp.response, "body", None)
            parsed = _coerce_payload_to_json(body)
            if parsed is None:
                continue
            products = _extract_products_from_payload(parsed, max_items=max_items)
            for item in products:
                key = (item.get("title", ""), item.get("shop", ""))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if max_items is not None and max_items > 0 and len(merged) >= max_items:
                    break

            if idx % 3 == 2:
                page.scroll.to_bottom()
                page.wait(random.uniform(0.8, 2.0))

        return merged
    except Exception as e:
        _debug_log(f"browser API fetch failed: {e}")
        return []
    finally:
        if own_page:
            try:
                page.quit()
            except Exception:
                pass


def _fetch_products_from_browser_dom(
    keyword: str,
    cookie_string: str = "",
    max_items: Optional[int] = None,
    scroll_times: int = 3,
    wait_seconds: float = 1.5,
    page: Optional["ChromiumPage"] = None,
) -> List[ProductItem]:
    """
    直接访问搜索页，从渲染后的 DOM 提取商品信息。
    """
    if ChromiumPage is None:
        return []

    url = f"https://s.taobao.com/search?q={quote(keyword)}"
    own_page = page is None
    if own_page:
        page = ChromiumPage()
        page.get("https://www.taobao.com/")
        page.wait(1)
        _inject_cookies_to_page(page, cookie_string)

    try:
        page.get(url)
        page.wait(2.5)
        for _ in range(max(scroll_times, 0)):
            page.scroll.to_bottom()
            page.wait(random.uniform(wait_seconds * 0.7, wait_seconds * 1.5))

        js = (Path(__file__).parent / "extract_products.js").read_text(encoding="utf-8")
        raw_items = page.run_js(js) or []
        if not isinstance(raw_items, list):
            return []

        products: List[ProductItem] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            title = _as_text(item.get("title"))
            if not title:
                continue
            products.append(
                {
                    "title": title,
                    "price": _as_text(item.get("price")),
                    "sales": _as_text(item.get("sales")),
                    "shop": _as_text(item.get("shop")),
                    "url": _as_text(item.get("url")),
                }
            )
            if max_items is not None and max_items > 0 and len(products) >= max_items:
                break
        return products
    except Exception as e:
        _debug_log(f"browser DOM fetch failed: {e}")
        return []
    finally:
        if own_page:
            try:
                page.quit()
            except Exception:
                pass


def _is_login_page(html: str, current_url: str) -> bool:
    """根据 URL 和页面文本粗略判断是否处于登录页。"""
    lower_url = (current_url or "").lower()
    if any(hint in lower_url for hint in _LOGIN_URL_HINTS):
        return True
    return any(text in (html or "") for text in _LOGIN_TEXT_HINTS)


def _fetch_html_by_browser(
    url: str,
    wait_seconds: int = 5,
    allow_manual_login: bool = False,
    login_timeout: int = 180,
    cookie_string: str = "",
    page: Optional["ChromiumPage"] = None,
) -> str:
    """
    使用浏览器渲染页面后获取 HTML。

    说明：
    - requests 在淘宝场景经常只能拿到壳页面，商品数据通过前端渲染；
    - 此回退方案可提高命中率。
    """
    if ChromiumPage is None:
        return ""

    own_page = page is None
    if own_page:
        page = ChromiumPage()
        page.get("https://www.taobao.com/")
        page.wait(1)
        _inject_cookies_to_page(page, cookie_string)

    try:
        page.get(url)
        page.wait(wait_seconds)
        html = page.html or ""
        if _is_login_page(html, page.url):
            if not allow_manual_login:
                return ""
            print("\n检测到淘宝登录页面，请在浏览器中手动完成登录。")
            print("登录完成后请回到终端按回车继续...")
            try:
                input()
            except EOFError:
                return ""

            deadline = time.time() + max(login_timeout, 10)
            while time.time() < deadline:
                page.get(url)
                page.wait(wait_seconds)
                html = page.html or ""
                if not _is_login_page(html, page.url):
                    return html
                time.sleep(2)
            return ""

        return html
    except Exception as e:
        _debug_log(f"browser HTML fetch failed: {e}")
        return ""
    finally:
        if own_page:
            try:
                page.quit()
            except Exception:
                pass


def search_taobao_products(
    keyword: str,
    timeout: int = 15,
    max_items: Optional[int] = None,
    use_browser_fallback: bool = True,
    allow_manual_login: bool = False,
    cookie_string: str = "",
) -> List[ProductItem]:
    """
    输入关键词，返回商品信息列表。

    Args:
        keyword: 搜索关键词，例如 "口罩"
        timeout: 请求超时时间（秒）
        max_items: 最多返回条数，None 表示不限制
        use_browser_fallback: requests 解析为空时，是否尝试浏览器渲染回退
        allow_manual_login: 浏览器回退时，是否允许手动登录后继续抓取
        cookie_string: 可选，手动传入 Cookie 字符串以复用登录态

    Returns:
        商品信息列表，每项字段：
        - title: 商品标题
        - price: 商品价格
        - sales: 销量文案（搜索页直接抓取，未做归一化）
        - shop: 店铺名称
    """
    cleaned_keyword = (keyword or "").strip()
    if not cleaned_keyword:
        return []

    url = f"https://s.taobao.com/search?q={quote(cleaned_keyword)}"
    request_cookies = _parse_cookie_string(cookie_string)

    # 带指数退避的请求重试
    response = None
    for attempt in range(3):
        try:
            response = requests.get(
                url,
                headers=_DEFAULT_HEADERS,
                cookies=request_cookies or None,
                timeout=timeout,
            )
            response.raise_for_status()
            break
        except requests.RequestException as e:
            _debug_log(f"requests attempt {attempt + 1} failed: {e}")
            response = None
            if attempt < 2:
                time.sleep(random.uniform(1, 2 ** (attempt + 1)))

    html = response.text if response is not None else ""
    results = _extract_from_html(html, max_items=max_items) if html else []
    if results:
        return results

    # 浏览器回退：复用同一个实例，避免反复启动/销毁浏览器
    if not use_browser_fallback or ChromiumPage is None:
        return []

    page = ChromiumPage()
    try:
        page.get("https://www.taobao.com/")
        page.wait(1)
        _inject_cookies_to_page(page, cookie_string)

        dom_results = _fetch_products_from_browser_dom(
            cleaned_keyword,
            cookie_string=cookie_string,
            max_items=max_items,
            page=page,
        )
        if dom_results:
            return dom_results

        api_results = _fetch_products_by_browser_api(
            cleaned_keyword,
            cookie_string=cookie_string,
            max_items=max_items,
            page=page,
        )
        if api_results:
            return api_results

        rendered_html = _fetch_html_by_browser(
            url,
            allow_manual_login=allow_manual_login,
            cookie_string=cookie_string,
            page=page,
        )
        if not rendered_html:
            return []
        return _extract_from_html(rendered_html, max_items=max_items)
    except Exception as e:
        _debug_log(f"browser fallback chain failed: {e}")
        return []
    finally:
        try:
            page.quit()
        except Exception:
            pass


def search_batch(
    keywords: List[str],
    max_items_per_keyword: Optional[int] = None,
    cookie_string: str = "",
    delay_range: tuple[float, float] = (2.0, 5.0),
) -> Dict[str, List[ProductItem]]:
    """批量搜索多个关键词，复用同一个浏览器实例。

    Args:
        keywords: 关键词列表
        max_items_per_keyword: 每个关键词最多返回条数
        cookie_string: Cookie 字符串
        delay_range: 每次搜索间的随机延迟范围（秒）

    Returns:
        {keyword: [ProductItem, ...]} 映射
    """
    results: Dict[str, List[ProductItem]] = {}
    if not keywords:
        return results

    if ChromiumPage is None:
        for kw in keywords:
            results[kw] = search_taobao_products(
                kw,
                max_items=max_items_per_keyword,
                use_browser_fallback=False,
                cookie_string=cookie_string,
            )
        return results

    page = ChromiumPage()
    try:
        page.get("https://www.taobao.com/")
        page.wait(1)
        _inject_cookies_to_page(page, cookie_string)

        for idx, kw in enumerate(keywords):
            kw = (kw or "").strip()
            if not kw:
                continue

            if idx > 0:
                time.sleep(random.uniform(*delay_range))

            items = _fetch_products_from_browser_dom(
                kw,
                cookie_string=cookie_string,
                max_items=max_items_per_keyword,
                page=page,
            )
            if not items:
                items = _fetch_products_by_browser_api(
                    kw,
                    cookie_string=cookie_string,
                    max_items=max_items_per_keyword,
                    page=page,
                )
            results[kw] = items
    except Exception as e:
        _debug_log(f"search_batch failed at keyword index {idx}: {e}")
    finally:
        try:
            page.quit()
        except Exception:
            pass

    return results


def main() -> None:
    """命令行测试入口。"""
    keyword = input("请输入关键词：").strip()
    cookie_string = os.getenv("TAOBAO_COOKIE", "").strip()
    if cookie_string:
        print("检测到环境变量 TAOBAO_COOKIE，将尝试复用登录态。")
    products = search_taobao_products(
        keyword,
        allow_manual_login=False,
        cookie_string=cookie_string,
    )
    print(f"共返回 {len(products)} 条商品信息")
    for index, product in enumerate(products, 1):
        print(
            f"{index}. 商品名称：{product['title']} | 价格：{product['price']} | "
            f"销量：{product['sales']} | 店铺：{product['shop']}"
        )


if __name__ == "__main__":
    main()
