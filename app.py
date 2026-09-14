"""
BUYMA 出品者チェックツール (Streamlit)

気になる出品者のページURLを貼るだけで、
「そのブランドをどれくらい動かしているか / 売れているか / 利益が出せそうか / 相場」
をまとめて確認するツール。ログイン不要・無料。
Streamlit Community Cloud にそのままデプロイできます。
"""

import calendar
import json
import re
import statistics
import datetime as dt
from collections import Counter
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, urljoin, quote_plus

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="BUYMA 出品者チェックツール", page_icon="🛍️", layout="wide")

TODAY = dt.date.today()
FEE_RATE = 0.077  # BUYMA 手数料 7.7%

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 商品名 → カテゴリー のキーワード（上にあるものほど優先）。小文字で比較します。
CATEGORY_KEYWORDS = [
    ("バッグ", ["バッグ", "トート", "ショルダー", "クラッチ", "ハンドバッグ", "リュック",
              "バックパック", "ボストン", "ポシェット", "bag", "tote"]),
    ("財布・小物", ["財布", "ウォレット", "カードケース", "キーケース", "コインケース",
                "名刺入れ", "パスケース", "ポーチ", "wallet", "cardholder", "card holder"]),
    ("靴・スニーカー", ["スニーカー", "シューズ", "ブーツ", "サンダル", "パンプス", "ローファー",
                  "ヒール", "モカシン", "バレエシューズ", "sneaker", "shoes", "boots", "loafer"]),
    ("ワンピース・ドレス", ["ワンピース", "ドレス", "dress", "gown", "onepiece", "one-piece"]),
    ("トップス", ["tシャツ", "ティーシャツ", "カットソー", "シャツ", "ニット", "ブラウス", "パーカー",
              "パーカ", "スウェット", "セーター", "tee", "t-shirt", "shirt", "hoodie", "knit",
              "sweater", "sweatshirt"]),
    ("アウター", ["コート", "ジャケット", "ブルゾン", "ダウン", "アウター", "トレンチ",
              "coat", "jacket", "blouson", "outer", "parka"]),
    ("ボトムス", ["パンツ", "デニム", "スカート", "ジーンズ", "ショートパンツ", "レギンス",
              "スラックス", "チノ", "pants", "denim", "skirt", "jeans", "shorts", "trouser", "leggings"]),
    ("アクセサリー", ["ネックレス", "ブレスレット", "ピアス", "イヤリング", "リング", "指輪",
                 "アンクレット", "ブローチ", "necklace", "bracelet", "ring", "earring", "pendant"]),
    ("帽子", ["帽子", "キャップ", "ハット", "ニット帽", "ベレー", "バケットハット",
            "cap", "hat", "beanie", "bucket"]),
    ("ベルト", ["ベルト", "belt"]),
    ("マフラー・ストール・スカーフ", ["マフラー", "ストール", "スカーフ", "ショール", "スヌード",
                          "scarf", "stole", "muffler"]),
    ("サングラス・メガネ", ["サングラス", "メガネ", "眼鏡", "アイウェア", "sunglass", "sunglasses",
                    "eyewear", "glasses"]),
    ("時計", ["時計", "ウォッチ", "watch"]),
    ("キーホルダー・チャーム", ["キーホルダー", "キーリング", "チャーム", "バッグチャーム",
                     "keyring", "key ring", "charm", "key holder"]),
]

NOISE_RE = re.compile(
    r"(送料無料|国内発送|国内即発|即発送|即納|正規品|新作|人気|話題|大人気|限定|セール|SALE|"
    r"最終|訳あり|関税込み?|直営店|買付|VIP|ラッピング無料|返品可|新品|未使用)",
    re.IGNORECASE,
)

# 記号だけの飾り（絵文字・ハート・感嘆符の連続など）をブランド名判定の前に落とす
DECOR_RE = re.compile(r"[♡♥♪☆★!！☀-➿]+")


# ============================ 取得まわり ============================
@st.cache_data(ttl=1800, show_spinner=False)
def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def soupify(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _url_shape(u: str) -> str:
    """URLのパス部分の数字を # に置き換えた「形」。ページ送りリンクの仲間はずれ検出に使う。"""
    return re.sub(r"\d+", "#", urlparse(u).path)


def find_pagination_targets(html: str, base_url: str):
    """ページ内の「2」「3」…や「最後」リンクの実URLを集める。
    BUYMAはページ送りのURL方式がページの種類ごとに違う（?page=2 / item_2.html / -B123_2/ など）ため、
    自分でURLを組み立てず、実際に置かれているリンクをそのまま使うことで方式の変更に強くする。
    ついでに関係ない「0」「評価件数」等の数字リンクを、URLの形が仲間はずれなことを手がかりに除く。"""
    soup = soupify(html)
    numbered, last_href = {}, None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("javascript"):
            continue
        t = a.get_text(strip=True)
        full = urljoin(base_url, href)
        if t.isdigit() and t != "0":
            numbered.setdefault(int(t), []).append(full)
        elif t in ("最後", "最後へ", "Last", "last") and last_href is None:
            last_href = full

    shape_counts = Counter(_url_shape(u) for urls in numbered.values() for u in urls)
    if last_href:
        shape_counts[_url_shape(last_href)] += 1
    if not shape_counts:
        return {}, None
    dominant, _ = shape_counts.most_common(1)[0]

    clean = {}
    for n, urls in numbered.items():
        for u in urls:
            if _url_shape(u) == dominant:
                clean[n] = u
                break
    last_url = last_href if last_href and _url_shape(last_href) == dominant else None
    return clean, last_url


# ============================ 画像URL → 出品日 ============================
def parse_yymmdd(s: str):
    """'240815' のような6桁を 2024-08-15 に変換。ありえない日付は None。"""
    try:
        yy, mm, dd = int(s[:2]), int(s[2:4]), int(s[4:6])
        d = dt.date(2000 + yy, mm, dd)
    except (ValueError, IndexError):
        return None
    if dt.date(2008, 1, 1) <= d <= TODAY + dt.timedelta(days=1):
        return d
    return None


def date_from_image_url(url: str):
    """BUYMAの商品画像URLに埋め込まれた出品日(YYMMDD)を拾う。"""
    if not url:
        return None
    for m in re.finditer(r"(?<!\d)(\d{6})(?!\d)", url):
        d = parse_yymmdd(m.group(1))
        if d:
            return d
    return None


# ============================ HTMLパーサ（壊れにくめに） ============================
def img_src(img) -> str:
    cands = []
    for attr in ("data-src", "data-original", "data-lazy-src", "data-lazysrc", "src"):
        v = img.get(attr)
        if v:
            cands.append(v.strip())
    ss = img.get("srcset") or img.get("data-srcset")
    if ss:
        cands.append(ss.split(",")[0].strip().split(" ")[0])
    for v in cands:
        if "item_photos" in v or "imgdata/item" in v:
            return v
    return cands[0] if cands else ""


def is_item_image(src: str) -> bool:
    return bool(src) and ("item_photos" in src or "imgdata/item" in src)


def extract_name(card, img) -> str:
    name = (img.get("alt") or "").strip()
    if not name:
        a = card.find("a", href=True)
        if a:
            name = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
    return re.sub(r"\s+", " ", name)[:160]


def extract_price(text: str):
    for pat in (r"[¥￥]\s*([\d,]{3,})", r"([\d,]{3,})\s*円"):
        for m in re.finditer(pat, text):
            try:
                v = int(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if 500 <= v <= 5_000_000:
                return v
    return None


def _photo_count(node) -> int:
    return sum(1 for i in node.find_all("img") if is_item_image(img_src(i)))


def closest_card(node):
    """商品画像から「1商品ぶんの情報（名前・価格・日付など）がまとまっている」
    一番大きい親要素まで登る。目印はタグ名やクラス名ではなく「商品画像が1枚だけ」であること
    ――他の商品の画像も入ってしまった時点（2枚以上になった時点）の1つ手前で止める。
    クラス名に依存しないぶん、BUYMA側のテンプレート変更に強い。"""
    cur = node
    for _ in range(10):
        nxt = cur.parent
        if nxt is None or nxt.name in ("body", "html"):
            break
        if _photo_count(nxt) > 1:
            break  # これ以上登ると別の商品の画像と混ざってしまう
        cur = nxt
    return cur


def parse_listing_page(html: str, base_url: str) -> dict:
    soup = soupify(html)
    items, seen = [], set()

    for img in soup.find_all("img")[:600]:
        src = img_src(img)
        if not is_item_image(src):
            continue
        key = src.split("?")[0]
        if key in seen:
            continue
        seen.add(key)

        card = closest_card(img)
        ctext = card.get_text(" ", strip=True)
        a = card.find("a", href=True)
        href = urljoin(base_url, a["href"]) if a else None
        name = extract_name(card, img)

        items.append({
            "name": name or "(商品名を取得できませんでした)",
            "url": href,
            "image": src,
            "price": extract_price(ctext),
            "listed_on": date_from_image_url(src),
        })

    # このブランドの出品総数
    text = soup.get_text(" ", strip=True)
    total = None
    m = re.search(r"(?:該当件数|出品商品件数|全)\s*([\d,]+)\s*件", text)
    if m:
        total = int(m.group(1).replace(",", ""))
    else:
        counts = [int(x.replace(",", "")) for x in re.findall(r"([\d,]{1,9})\s*件", text)]
        counts = [c for c in counts if c >= max(1, len(items))]
        total = max(counts) if counts else (len(items) or None)

    return {"items": items, "total_count": total}


def load_listing(url: str, html_text: str, back_pages: int = 3):
    """② ブランド一覧ページ。新着順の最後の方も数ページさかのぼって最古の出品日を探す。"""
    if html_text and html_text.strip():
        pr = parse_listing_page(html_text, "https://www.buyma.com/")
        return pr["items"], pr["total_count"], 1, []
    if not url or not url.strip():
        return [], None, 1, ["② のURLもHTMLも入力されていません。"]

    url = url.strip()
    try:
        first = fetch(url)
    except Exception as e:  # noqa: BLE001
        return [], None, 1, [
            f"② ページを取得できませんでした（{e}）。ページを開いて右クリック→"
            "「ページのソースを表示」→全選択コピーして、HTML貼り付け欄に入れてください。"
        ]

    pr = parse_listing_page(first, url)
    items = list(pr["items"])

    numbered, last_url = find_pagination_targets(first, url)
    targets = [last_url] if last_url else []
    for n in sorted(numbered, reverse=True):
        if len(targets) >= back_pages + 1:
            break
        if numbered[n] not in targets:
            targets.append(numbered[n])
    last_page = max([*numbered.keys()], default=1)

    fetched = {url}
    for t in targets:
        if not t or t in fetched:
            continue
        fetched.add(t)
        try:
            items.extend(parse_listing_page(fetch(t), t)["items"])
        except Exception:  # noqa: BLE001
            pass

    seen, dedup = set(), []
    for it in items:
        k = it["image"].split("?")[0]
        if k in seen:
            continue
        seen.add(k)
        dedup.append(it)
    return dedup, pr["total_count"], last_page, []


def parse_sales_page(html: str):
    """注文実績ページから {"date": 販売日, "name": 商品名, "text": カード内の全文, "item_id": 商品ID}
    のリストを返す。ブランド名によるしぼり込みは、name だけでなく text（カード内の見えている文字全部）
    に対しても行う（name の取得に失敗していても text 側でブランド名を拾えることが多いため）。
    item_id は「特定の1商品が売れたか」を確認するときに使う。"""
    soup = soupify(html)
    date_re = re.compile(r"20(\d{2})\s*[./年\-]\s*(\d{1,2})\s*[./月\-]\s*(\d{1,2})")

    def to_date(m):
        try:
            d = dt.date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
        return d if dt.date(2008, 1, 1) <= d <= TODAY else None

    orders = []
    item_imgs = [i for i in soup.find_all("img") if is_item_image(img_src(i))]
    for img in item_imgs:
        card = closest_card(img)
        ctext = card.get_text(" ", strip=True)
        m = date_re.search(ctext)
        if m:
            d = to_date(m)
            if d:
                a = card.find("a", href=True)
                idm = re.search(r"/item/(\d+)/", a["href"]) if a else None
                orders.append({
                    "date": d, "name": extract_name(card, img), "text": ctext,
                    "item_id": idm.group(1) if idm else None,
                })

    if not orders:  # 画像が拾えないレイアウト向けのフォールバック（商品名・IDは取得できない）
        for m in date_re.finditer(soup.get_text(" ", strip=True)):
            d = to_date(m)
            if d:
                orders.append({"date": d, "name": "", "text": "", "item_id": None})
    return orders


def check_item_sold(seller_id: str, item_id: str, max_pages: int = 5):
    """出品者の注文実績ページを数ページさかのぼり、指定した商品IDの注文が見つかるか確認する。"""
    base_url = f"https://www.buyma.com/buyer/{seller_id}/sales_1.html"
    checked_pages = 0
    for n in range(1, max_pages + 1):
        url = base_url if n == 1 else re.sub(r"sales_\d+\.html", f"sales_{n}.html", base_url)
        try:
            html = fetch(url)
        except Exception:  # noqa: BLE001
            break
        orders = parse_sales_page(html)
        if not orders:
            break
        checked_pages += 1
        for o in orders:
            if o.get("item_id") == item_id:
                return {"found": True, "date": o["date"], "checked_pages": checked_pages}
        if len(orders) < 5:
            break
    return {"found": False, "date": None, "checked_pages": checked_pages}


def load_sales(url: str, html_text: str, max_pages: int = 12):
    """③ 注文実績ページ。sales_1.html → sales_2.html … と自動でめくる。"""
    if html_text and html_text.strip():
        return parse_sales_page(html_text), []
    if not url or not url.strip():
        return [], ["③ のURLもHTMLも未入力のため、注文実績のチェックはスキップします。"]

    url = url.strip()
    can_paginate = bool(re.search(r"sales_\d+\.html", url))
    all_orders, errors = [], []
    pages = max_pages if can_paginate else 1

    for n in range(1, pages + 1):
        page_url = re.sub(r"sales_\d+\.html", f"sales_{n}.html", url) if can_paginate else url
        try:
            html = fetch(page_url)
        except Exception as e:  # noqa: BLE001
            if n == 1:
                errors.append(f"③ ページを取得できませんでした（{e}）。HTML貼り付け欄をご利用ください。")
            break
        ords = parse_sales_page(html)
        if not ords:
            break
        all_orders.extend(ords)
        if len(ords) < 5:  # 最終ページらしい
            break
    return all_orders, errors


def extract_country(html: str):
    """プロフィールページに表示されている国旗画像から、出品者の拠点国を取得する。"""
    m = re.search(r'<img[^>]+src="[^"]*flag/[^"]*"[^>]*alt="([^"]+)"', html or "")
    return m.group(1).strip() if m else None


def guess_seller_id(url: str = "", html: str = ""):
    """URLやページ内のリンクから出品者ID（数字）を推測する。
    /buyer/12345/... 形式、/r/-B12345.../ 形式のどちらにも対応。"""
    for pat in (r"/buyer/(\d+)/", r"-B(\d+)"):
        m = re.search(pat, url or "")
        if m:
            return m.group(1)
    m = re.search(r'href="/buyer/(\d+)\.html"', html or "")
    return m.group(1) if m else None


def load_profile(url: str, html_text: str) -> dict:
    html = None
    if html_text and html_text.strip():
        html = html_text
    elif url and url.strip():
        try:
            html = fetch(url.strip())
        except Exception:  # noqa: BLE001
            html = None
    if not html:
        return {"name": None, "country": None}
    soup = soupify(html)
    name = None
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        name = og["content"].strip()
    if not name and soup.title:
        name = soup.title.get_text(strip=True)
    if name:
        name = re.split(r"[|｜/／\-–—]", name)[0].strip()
    return {"name": name or None, "country": extract_country(html)}


# ---------------- 商品1点ぶんの価格チェック用 ----------------
def _iter_jsonld(html: str):
    """ページ内の <script type="application/ld+json"> をパースして順に返す。壊れているものは無視。"""
    for tag in soupify(html).find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        yield from (data if isinstance(data, list) else [data])


def _find_offers(node):
    """JSON-LDの中から Offer / AggregateOffer を、ネストの深さに関係なく再帰的に探す。"""
    found = []
    if isinstance(node, dict):
        if node.get("@type") in ("Offer", "AggregateOffer") and node.get("price") not in (None, ""):
            found.append(node)
        for v in node.values():
            found.extend(_find_offers(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_find_offers(v))
    return found


CURRENCY_PATTERNS = [
    (r"[¥￥]\s*([\d,]{2,})", "JPY"),
    (r"\$\s*([\d,]+(?:\.\d{1,2})?)", "USD"),
    (r"£\s*([\d,]+(?:\.\d{1,2})?)", "GBP"),
    (r"€\s*([\d,]+(?:\.\d{1,2})?)", "EUR"),
]


def extract_price_generic(html: str):
    """商品ページから価格を推測する（BUYMA以外の、任意の仕入れ先ページ向け）。
    まず構造化データ（JSON-LD の Product/Offer。多くのECサイトがSEO目的で埋め込んでいる）を試し、
    無ければ通貨記号のパターンで探す。見つかれば (金額, 通貨) を返す。サイトによっては検出できない。"""
    for node in _iter_jsonld(html):
        for offer in _find_offers(node):
            try:
                amount = float(str(offer["price"]).replace(",", ""))
            except (ValueError, TypeError):
                continue
            if amount > 0:
                return amount, (offer.get("priceCurrency") or "").upper()
    text = soupify(html).get_text(" ", strip=True)
    for pat, cur in CURRENCY_PATTERNS:
        m = re.search(pat, text)
        if m:
            try:
                amount = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if amount > 0:
                return amount, cur
    return None


def extract_shipping_hint(html: str):
    """仕入れ先ページの構造化データに、送料の情報が書かれていれば拾う。
    サイトによっては「国内配送は無料」「$100以上で無料」など複数の条件を同時に載せていることが多く、
    どれが実際に日本への発送に適用されるかは自動では判断できない。そのため見つかった候補を
    全部そのままリストで返す（1つに決め打ちしない）。呼び出し側は「参考情報」として提示するだけにし、
    自動で入力欄を埋めるのには使わない。"""
    found = []
    for node in _iter_jsonld(html):
        for offer in _find_offers(node):
            sd = offer.get("shippingDetails")
            for one in (sd if isinstance(sd, list) else [sd] if sd else []):
                if not isinstance(one, dict):
                    continue
                sr = one.get("shippingRate")
                for r in (sr if isinstance(sr, list) else [sr] if sr else []):
                    if isinstance(r, dict) and r.get("value") is not None:
                        try:
                            val = float(r["value"])
                        except (TypeError, ValueError):
                            continue
                        if val >= 0:
                            pair = (val, (r.get("currency") or "").upper())
                            if pair not in found:
                                found.append(pair)
    return found or None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fx_rate(currency: str):
    """1単位の外貨が何円かを調べる（無料・無料枠のFrankfurter APIを利用。課金は発生しない）。
    取得できたら (レート, 基準日の文字列) を返す。取得できなければ None。"""
    currency = (currency or "").upper().strip()
    if not currency or currency == "JPY":
        return 1.0, None
    try:
        r = requests.get(
            "https://api.frankfurter.dev/v1/latest",
            params={"from": currency, "to": "JPY"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        rate = data.get("rates", {}).get("JPY")
        if rate:
            return float(rate), data.get("date")
    except Exception:  # noqa: BLE001
        pass
    return None


def parse_buyma_product(html: str) -> dict:
    """BUYMAの商品ページ（1商品）から、名前・ブランド・実際の販売価格・画像・
    商品ID・出品者ID・出品日を取り出す。
    BUYMAは商品ページに schema.org の構造化データ（JSON-LD）を必ず埋め込んでいるため、
    それを優先して読む（DOMのクラス名に依存しないので、ページデザインの変更に強い）。"""
    result = {
        "name": None, "brand": None, "price": None, "image": None,
        "item_id": None, "seller_id": None, "listed_on": None,
    }
    for node in _iter_jsonld(html):
        if not isinstance(node, dict) or node.get("@type") not in ("Product", "ProductGroup"):
            continue
        result["name"] = result["name"] or node.get("name")
        brand = node.get("brand")
        if isinstance(brand, dict):
            result["brand"] = result["brand"] or brand.get("name")

        if result["item_id"] is None:
            gid = node.get("productGroupID")
            if gid:
                result["item_id"] = str(gid)
            else:
                idm = re.search(r"/item/(\d+)/", str(node.get("@id") or ""))
                if idm:
                    result["item_id"] = idm.group(1)

        variant = node
        if node.get("@type") == "ProductGroup":
            variants = node.get("hasVariant") or []
            if variants and isinstance(variants[0], dict):
                variant = variants[0]
                result["name"] = result["name"] or variant.get("name")

        if result["price"] is None:
            offers = _find_offers(variant)
            if offers:
                try:
                    result["price"] = int(round(float(offers[0]["price"])))
                except (ValueError, TypeError):
                    pass

        img = variant.get("image") if isinstance(variant, dict) else None
        if isinstance(img, list) and img:
            result["image"] = result["image"] or img[0]
        elif isinstance(img, str):
            result["image"] = result["image"] or img

    soup = soupify(html)
    if result["price"] is None:
        m = re.search(r"[¥￥]\s*([\d,]{3,})", soup.get_text(" ", strip=True))
        if m:
            result["price"] = int(m.group(1).replace(",", ""))
    if not result["name"]:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            result["name"] = og["content"].strip()
    if result["item_id"] is None:
        idm = re.search(r"/item/(\d+)/", html)
        if idm:
            result["item_id"] = idm.group(1)

    m = re.search(r'href="/buyer/(\d+)\.html"', html)
    if m:
        result["seller_id"] = m.group(1)

    result["listed_on"] = date_from_image_url(result["image"] or "")
    return result


# ============================ 小さな計算・整形 ============================
def classify(name: str) -> str:
    low = (name or "").lower()
    for cat, kws in CATEGORY_KEYWORDS:
        if any(k in low for k in kws):
            return cat
    return "その他"


def clean_name(name: str) -> str:
    n = re.sub(r"[【】\[\]『』（）()｜|/《》〈〉★☆＿]+", " ", name or "")
    n = DECOR_RE.sub(" ", n)
    n = NOISE_RE.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


_BRAND_STOPWORDS = {
    "MEN'S", "WOMEN'S", "MENS", "WOMENS", "KIDS", "UNISEX",
    "GIRL'S", "BOY'S", "NEW", "SALE",
}


def guess_brand_from_name(name: str) -> str:
    """商品名の先頭の単語（1〜2語）からブランド名を推定する簡易ロジック。
    正式なブランド辞書は使っていないため、精度には限界がある（あくまで参考値）。"""
    n = clean_name(name)
    if not n:
        return ""
    tokens = [t for t in n.split(" ") if t]
    if not tokens:
        return ""
    picked = [tokens[0]]
    if (
        len(tokens) >= 2
        and tokens[1].upper() not in _BRAND_STOPWORDS
        and not any(c.isdigit() for c in tokens[1])
        and "-" not in tokens[1]
        and (tokens[1].isupper() or tokens[1][:1].isupper())
        and len(tokens[1]) <= 12
    ):
        picked.append(tokens[1])
    brand = " ".join(picked)
    if len(brand) < 2 or brand.isdigit():
        return ""
    return brand


def guess_model(name: str) -> str:
    """商品名から型番っぽい文字列を推測（取れないことも多い）。"""
    picks = []
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-_./]{3,}", name or ""):
        core = tok.strip("-_./")
        low = core.lower()
        if re.fullmatch(r"20\d{2}(ss|aw|fw|pf)?", low):
            continue
        has_d = any(c.isdigit() for c in core)
        has_a = any(c.isalpha() for c in core)
        if has_d and (has_a or len(re.sub(r"\D", "", core)) >= 5):
            if core not in picks:
                picks.append(core)
    return " ".join(picks[:2])


def img_search_url(image_url: str) -> str:
    return "https://lens.google.com/uploadbyurl?url=" + quote_plus(image_url)


def text_search_url(brand: str, name: str) -> str:
    model = guess_model(name)
    q = " ".join(x for x in [brand.strip(), model or clean_name(name)[:60]] if x).strip()
    return "https://www.google.com/search?q=" + quote_plus(q)


def yen(n) -> str:
    try:
        return f"¥{int(round(n)):,}"
    except (ValueError, TypeError):
        return "—"


def humanize_days(n: int) -> str:
    if n <= 0:
        return "今日"
    if n < 31:
        return f"約{n}日前"
    if n < 365:
        return f"約{round(n / 30.4)}ヶ月前"
    return f"約{n / 365:.1f}年前"


def _add_months(d: dt.date, months: int) -> dt.date:
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def month_day_diff(start: dt.date, end: dt.date) -> str:
    """start→end の日数を「Xヶ月Y日」の形にする（79日ではなく2ヶ月18日、のように分かりやすくする）。"""
    total_days = (end - start).days
    if total_days < 0:
        return f"{total_days}日"
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if _add_months(start, months) > end:
        months -= 1
    remainder = (end - _add_months(start, months)).days
    if months <= 0:
        return f"{total_days}日"
    if remainder == 0:
        return f"{months}ヶ月"
    return f"{months}ヶ月{remainder}日"


def humanize_duration(start: dt.date, end: dt.date) -> str:
    """start→end の期間を「1.3年」ではなく「1年3ヶ月」の形で表す。"""
    total_months = (end.year - start.year) * 12 + (end.month - start.month)
    if _add_months(start, total_months) > end:
        total_months -= 1
    if total_months <= 0:
        return "1ヶ月未満"
    years, months = divmod(total_months, 12)
    if years == 0:
        return f"{months}ヶ月"
    if months == 0:
        return f"{years}年"
    return f"{years}年{months}ヶ月"


def humanize_since(from_date: dt.date) -> str:
    """「最後の出品から」のような経過表示。1年未満は約N日前／約Nヶ月前、
    1年以上は「1.3年前」ではなく「1年3ヶ月前」の形にする。"""
    since_days = (TODAY - from_date).days
    if since_days < 365:
        return humanize_days(since_days)
    return f"{humanize_duration(from_date, TODAY)}前"


def month_key(d: dt.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_span(start: dt.date, end: dt.date):
    y, m, out = start.year, start.month, []
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def jp_month(key: str) -> str:
    y, m = key.split("-")
    return f"{int(y)}年{int(m)}月"


WATCHLIST_COLUMNS = [
    "追加日時", "出品者名", "拠点国", "ブランド名", "出品総数",
    "扱い始めた日", "出品ペース", "最終出品からの経過", "一覧URL", "プロフィールURL",
]


def add_to_watchlist(row: dict):
    """候補リスト（st.session_state）に1行追加する。同じ「一覧URL」が既にあれば上書きする。"""
    wl = st.session_state.setdefault("watchlist", [])
    key = row.get("一覧URL")
    for i, existing in enumerate(wl):
        if key and existing.get("一覧URL") == key:
            wl[i] = row
            return
    wl.append(row)


# ============================ 画面：① 出品者チェック ============================
def render_seller_tool():
    st.title("🛍️ BUYMA 出品者チェックツール")
    st.write(
        "気になる出品者のページURLを貼るだけで、**そのブランドをどれくらい動かしているか / "
        "売れているか / 相場**をまとめて確認します。"
    )
    st.caption("💰 利益が出せそうかを調べたいときは「商品ごとの価格チェック」タブをお使いください。")

    with st.expander("使い方（クリックで開く）"):
        st.markdown(
            "1. 調べたい出品者のページを3つ用意します。\n"
            "   - ① プロフィールページ（例：`https://www.buyma.com/buyer/0000000.html`）\n"
            "   - ② その出品者のページで **対象ブランドにしぼり込み → 並び替えを「新着順」** にした一覧ページ\n"
            "   - ③ 注文実績ページ（例：`https://www.buyma.com/buyer/0000000/sales_1.html`）\n"
            "2. 「チェックする」を押すと、下に結果が出ます。\n\n"
            "※ ブランド全体の競合出品者数などは、ブランドページでご自身で確認してください（このツールでは扱いません）。"
        )

    with st.form("inputs"):
        c1, c2 = st.columns(2)
        with c1:
            profile_url = st.text_input("① 出品者プロフィールページのURL",
                                        placeholder="https://www.buyma.com/buyer/0000000.html")
            brand_url = st.text_input("② 対象ブランドにしぼった「新着順」一覧ページのURL",
                                      placeholder="ブランドで絞り込み→並び替えを新着順にしたページのURL")
        with c2:
            sales_url = st.text_input("③ 注文実績ページのURL",
                                      placeholder="https://www.buyma.com/buyer/0000000/sales_1.html")
            brand_name = st.text_input("対象ブランド名（仕入れ先さがしの検索に使います）", placeholder="例）LOEWE")
        with st.expander("💡 URLで読み込めないとき（Community Cloud でブロックされる場合など）はHTMLを貼り付け"):
            st.caption("各ページをブラウザで開き、右クリック →「ページのソースを表示」→ 全選択してコピー → ここに貼り付け。")
            profile_html = st.text_area("① プロフィールページのHTML", height=68)
            brand_html = st.text_area("② ブランド一覧ページのHTML", height=68)
            sales_html = st.text_area("③ 注文実績ページのHTML", height=68)
        go = st.form_submit_button("チェックする", type="primary", use_container_width=True)

    if go:
        with st.spinner("BUYMAのページを読み込み中…（10〜30秒ほどかかることがあります）"):
            items, total_count, last_page, e1 = load_listing(brand_url, brand_html)
            orders, e2 = load_sales(sales_url, sales_html)
            profile = load_profile(profile_url, profile_html)
        st.session_state["result"] = dict(
            items=items, total_count=total_count, last_page=last_page,
            orders=sorted(orders, key=lambda o: o["date"]), profile=profile, brand_name=brand_name,
            profile_url=profile_url.strip(), brand_url=brand_url.strip(),
            errors=[m for m in (*e1, *e2) if m],
        )

    res = st.session_state.get("result")
    if not res:
        st.info("上のフォームに3つのURLを入れて「チェックする」を押してください。")
        return

    items = res["items"]
    orders = res["orders"]

    for msg in res["errors"]:
        st.warning(msg)

    if not items:
        st.error(
            "② ブランド一覧ページから商品を読み取れませんでした。URLが「商品一覧ページ」になっているか確認するか、"
            "HTML貼り付けをお試しください。"
        )
        return

    if res["profile"].get("name"):
        st.subheader(f"対象出品者：{res['profile']['name']}")
    if res["profile"].get("country"):
        st.caption(f"🌍 拠点国：{res['profile']['country']}")

    dated = sorted(it["listed_on"] for it in items if it["listed_on"])
    oldest = dated[0] if dated else None
    newest = dated[-1] if dated else None
    total_disp = res["total_count"] or len(items)

    # 出品ペースの月別推移（「直近で出品がコンスタントになったか」を見るため、2.の売れ行きと並べて使う）
    listing_months = month_span(oldest, newest) if oldest and newest else []
    listing_monthly = Counter(month_key(d) for d in dated)
    listing_overall_avg = (len(dated) / len(listing_months)) if listing_months else None
    listing_recent_avg = None
    listing_trend = None
    if len(listing_months) >= 4:
        lm_recent = listing_months[-3:]
        listing_recent_avg = sum(listing_monthly.get(k, 0) for k in lm_recent) / len(lm_recent)
        if listing_recent_avg > listing_overall_avg * 1.3:
            listing_trend = "up"
        elif listing_recent_avg < listing_overall_avg * 0.6:
            listing_trend = "down"
        else:
            listing_trend = "flat"

    # ---------------------------------------------------------------- 1
    st.header("1. ブランドの出品状況")

    if oldest and newest and total_disp:
        span_days = (newest - oldest).days
        pace = span_days / total_disp
        pace_text = f"平均 {pace:.1f} 日に1点" if pace >= 0.1 else "ほぼ毎日"
    else:
        pace = None
        pace_text = "算出不可"

    since = (TODAY - newest).days if newest else None

    status_rows = [
        ("このブランドの出品総数", f"{total_disp:,} 点"),
        ("このブランドを扱い始めた日", f"{oldest.year}年{oldest.month}月{oldest.day}日" if oldest else "取得できず"),
        ("出品ペース", pace_text),
        ("最後の出品から", humanize_since(newest) if newest else "取得できず"),
    ]
    st.table(pd.DataFrame(status_rows, columns=["項目", "値"]).set_index("項目"))

    if st.button("✅ このブランド・出品者を候補リストに追加", key="add_watchlist_seller"):
        add_to_watchlist({
            "追加日時": f"{TODAY.year}/{TODAY.month}/{TODAY.day}",
            "出品者名": res["profile"].get("name") or "（不明）",
            "拠点国": res["profile"].get("country") or "（不明）",
            "ブランド名": res["brand_name"] or "（未入力）",
            "出品総数": total_disp,
            "扱い始めた日": f"{oldest.year}/{oldest.month}/{oldest.day}" if oldest else "不明",
            "出品ペース": pace_text,
            "最終出品からの経過": humanize_since(newest) if newest else "不明",
            "一覧URL": res.get("brand_url") or "",
            "プロフィールURL": res.get("profile_url") or "",
        })
        st.success("候補リストに追加しました。「⭐ 候補リスト」タブから確認・ダウンロードできます。")

    if oldest:
        st.write(f"➡️ この出品者は、このブランドを **{humanize_duration(oldest, TODAY)}** 扱っています。")

    if since is not None and since >= 14:
        st.warning(f"⚠️ 最後の出品から{since}日たっています。**最近このブランドの出品が止まっている可能性**があります。")
    elif since is not None:
        st.success("✅ 直近も新しい商品を追加していて、活発に動かしています。")

    if res["total_count"] and len(dated) < res["total_count"] * 0.6:
        st.caption(
            f"※ 出品日を確認できたのは{len(dated)}点分です。新着順のページをさかのぼって確認していますが、"
            "実際の「扱い始めた日」はこれよりさらに前の可能性があります。"
        )

    if listing_months:
        st.subheader("出品ペースの推移（月別）")
        l_disp = listing_months[-24:]
        ldf = pd.DataFrame({"出品点数": [listing_monthly.get(k, 0) for k in l_disp]},
                           index=[jp_month(k) for k in l_disp])
        st.bar_chart(ldf, height=220)
        if len(listing_months) > len(l_disp):
            st.caption(f"※ グラフは直近{len(l_disp)}ヶ月分を表示しています。")
        if res["total_count"] and len(dated) < res["total_count"] * 0.6:
            st.caption(
                f"※ 取得できた出品{len(dated)}点（全{res['total_count']:,}点中）をもとにした月別集計です。"
                "出品数が多い出品者では、実際のペースと差があることがあります。"
            )
        if listing_trend == "up":
            st.success(
                f"✅ 直近3ヶ月の出品ペースは月{listing_recent_avg:.1f}点で、"
                f"全期間平均（月{listing_overall_avg:.1f}点）より増えています。出品がコンスタントになってきています。"
            )
        elif listing_trend == "down":
            st.warning(
                f"⚠️ 直近3ヶ月の出品ペースは月{listing_recent_avg:.1f}点で、"
                f"全期間平均（月{listing_overall_avg:.1f}点）より落ちています。"
            )
        elif listing_trend == "flat":
            st.info("出品ペースは大きな変化なく安定しています。")

    # ---------------------------------------------------------------- 2
    st.divider()
    st.header("2. 注文実績と売れ行き")
    st.caption("ログインが必要な情報（最近売れたアイテム 等）は取得しません。")

    brand = (res["brand_name"] or "").strip()
    def _order_matches(o, needle):
        hay = ((o.get("name") or "") + " " + (o.get("text") or "")).lower()
        return needle in hay

    brand_orders = [o for o in orders if brand and _order_matches(o, brand.lower())]

    if brand and brand_orders:
        use_orders = brand_orders
        st.info(
            f"🔎「{brand}」を含む注文にしぼり込んで表示しています（{len(brand_orders)}件 / "
            f"全ブランド合計{len(orders)}件中）。"
        )
    elif brand and orders:
        use_orders = orders
        st.warning(
            f"⚠️「{brand}」を含む注文は見つかりませんでした。**まだこのブランドが売れていない可能性**があります。"
            "（商品名の取得精度により、実際は売れていても見つからないことがあります）"
            "参考として、下は全ブランド合計の実績です。"
        )
    else:
        use_orders = orders
        if orders:
            st.caption(
                "ブランド名を入力すると、このブランドだけの実績にしぼり込めます。"
                "現在は全ブランド合計の実績です（このブランドだけの数字ではありません）。"
            )

    if not use_orders:
        st.info("公開されている注文実績が見つかりませんでした。実績がまだ少ない出品者か、注文実績を公開していない可能性があります。")
    else:
        is_brand_specific = use_orders is brand_orders
        dates = [o["date"] for o in use_orders]
        first_sale, last_sale = dates[0], dates[-1]
        months = month_span(first_sale, last_sale)
        monthly = Counter(month_key(d) for d in dates)
        total_sales = len(dates)
        avg_per_month = total_sales / len(months)

        a, b, c = st.columns(3)
        if oldest:
            lag = (first_sale - oldest).days
            a.metric("出品開始 → 初めて売れるまで", month_day_diff(oldest, first_sale) if lag >= 0 else "算出対象外")
            if lag is not None and lag >= 0:
                a.caption(
                    f"{oldest.year}年{oldest.month}月{oldest.day}日 ▶︎ "
                    f"{first_sale.year}年{first_sale.month}月{first_sale.day}日"
                )
        else:
            lag = None
            a.metric("初めて売れるまで", "出品日が不明")
        b.metric(
            f"確認できた販売件数{'（このブランド）' if is_brand_specific else ''}",
            f"{total_sales:,} 件",
            help=f"{first_sale:%Y/%m}〜{last_sale:%Y/%m} の公開分",
        )
        c.metric("月あたりの平均販売数", f"約 {avg_per_month:.1f} 件")

        if lag is not None and lag < 0:
            if is_brand_specific:
                st.caption(
                    "※ このブランドの出品開始日より前の日付の注文が見つかったため、初回販売までの日数は計算していません"
                    "（出品日をさかのぼりきれていない可能性があります）。"
                )
            else:
                st.caption("※ この出品者はこのブランドを扱う前から他ブランドの販売実績があるため、初回販売までの日数は計算していません。")

        st.markdown("**月ごとの数字（新しい月が上）**")
        brand_label = brand if is_brand_specific else "全ブランド"
        all_months = sorted(set(listing_months) | set(months), reverse=True)
        month_table = pd.DataFrame({
            "日付": [jp_month(k) for k in all_months],
            "ブランド名": [brand_label] * len(all_months),
            "出品数": [listing_monthly.get(k, 0) for k in all_months],
            "販売数": [monthly.get(k, 0) for k in all_months],
        })
        st.table(month_table.set_index("日付"))
        if not is_brand_specific:
            st.caption("※ 上の「販売数」はブランドを絞り込めていないため、全ブランド合計の件数です。")

        disp = months[-24:]
        df = pd.DataFrame({"販売件数": [monthly.get(k, 0) for k in disp]},
                          index=[jp_month(k) for k in disp])
        st.bar_chart(df, height=260)
        if len(months) > len(disp):
            st.caption(f"※ グラフは直近{len(disp)}ヶ月分を表示しています。")

        sales_trend = None
        if len(months) >= 4:
            recent = months[-3:]
            recent_avg = sum(monthly.get(k, 0) for k in recent) / len(recent)
            if recent_avg == 0:
                st.warning("⚠️ 直近3ヶ月は販売が確認できません。売れ行きが止まっている可能性があります。")
                sales_trend = "down"
            elif recent_avg < avg_per_month * 0.6:
                st.warning(
                    f"⚠️ 直近3ヶ月の平均は月{recent_avg:.1f}件で、全体平均（月{avg_per_month:.1f}件）より落ちています。失速ぎみです。"
                )
                sales_trend = "down"
            elif recent_avg > avg_per_month * 1.3:
                st.success(f"✅ 直近3ヶ月は月{recent_avg:.1f}件で、全体平均より伸びています。勢いがあります。")
                sales_trend = "up"
            else:
                st.info("売れ行きは大きなムラなく安定しています。")
                sales_trend = "flat"

            # 1.の「出品ペースの推移」と組み合わせて、売れ行きの変化と出品ペースの変化が
            # 同じ時期に起きていないかを見る（あくまで「重なっている」という参考情報で、因果関係の断定ではない）。
            if is_brand_specific and listing_trend and sales_trend:
                if listing_trend == "up" and sales_trend == "up":
                    st.info(
                        "💡 出品ペースが上がった時期と、販売が伸びた時期が重なっています。"
                        "出品を増やした（コンスタントに出すようになった）ことが、販売増につながっている可能性があります。"
                    )
                elif listing_trend == "down" and sales_trend == "down":
                    st.info(
                        "💡 出品ペースが落ちた時期と、販売が落ちた時期が重なっています。"
                        "出品が止まると売れ行きも落ちる傾向があるようです。"
                    )
                elif listing_trend == "flat" and sales_trend == "up":
                    st.info(
                        "💡 出品ペースは変わっていないのに、直近で販売が伸びています。"
                        "出品数以外の要因（口コミ・季節・値下げなど）が影響している可能性があります。"
                    )
                elif listing_trend == "up" and sales_trend in ("flat", "down"):
                    st.info(
                        "💡 出品は増えているのに、販売はまだそれに比例して伸びていません。"
                        "出品してから売れるまでにはタイムラグがあるため、もう少し様子を見てもよさそうです。"
                    )

    if orders:
        with st.expander("📊 参考：直近1年のブランド別 販売ランキング（推定）"):
            one_year_ago = TODAY - dt.timedelta(days=365)
            recent_all = [o for o in orders if o["date"] >= one_year_ago]
            brand_counts = Counter()
            unknown = 0
            for o in recent_all:
                b = guess_brand_from_name(o.get("name") or "")
                if b:
                    brand_counts[b] += 1
                else:
                    unknown += 1
            if not brand_counts:
                st.caption("商品名を取得できた注文が少なく、ランキングを作成できませんでした。")
            else:
                rank_rows = [{"ブランド（推定）": b, "販売件数": c} for b, c in brand_counts.most_common(15)]
                st.dataframe(pd.DataFrame(rank_rows), use_container_width=True, hide_index=True)
                st.caption(
                    f"直近1年の注文{len(recent_all)}件のうち、商品名からブランド名を推定できた"
                    f"{sum(brand_counts.values())}件を集計しています（{unknown}件は商品名を取得できず対象外）。"
                    "商品名の先頭の単語をブランド名とみなす簡易的な推定のため、精度には限界があります。"
                )

    # ---------------------------------------------------------------- 3
    st.divider()
    st.divider()
    st.header("3. カテゴリー別の相場（この出品者の場合）")

    by_cat: dict[str, list[int]] = {}
    for it in items:
        if it["price"]:
            by_cat.setdefault(classify(it["name"]), []).append(it["price"])

    if not by_cat:
        st.info("価格を読み取れる商品がありませんでした。")
    else:
        rows = [{
            "カテゴリー": cat,
            "商品数": len(ps),
            "平均価格": yen(statistics.mean(ps)),
            "価格帯（最安〜最高）": f"{yen(min(ps))} 〜 {yen(max(ps))}",
        } for cat, ps in by_cat.items()]
        rows.sort(key=lambda r: (r["カテゴリー"] == "その他", -r["商品数"]))
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.info(
            "この価格帯は「この出品者が扱っている商品の範囲」での目安です。ブランド全体の相場とは違うことがあります。"
            "商品名からの自動分類のため、「その他」に入る商品や分類ミスも一定数出ます。"
        )

    # ---------------------------------------------------------------- 4
    st.divider()
    st.header("4. 仕入れ先を探す")
    st.caption(
        "各商品について、似た品を外部サイトでさがすリンクです。ボタンを押すと Google の検索結果が新しいタブで開きます"
        "（無料・検索APIなし）。"
    )

    brand = res["brand_name"] or ""
    LIMIT = 60
    shown = items[:LIMIT]
    if len(items) > LIMIT:
        st.caption(f"※ 商品が多いため、新しい方から{LIMIT}件を表示しています。")

    for it in shown:
        col_img, col_info, col_b1, col_b2 = st.columns([1, 5, 2, 2])
        with col_img:
            if it["image"]:
                st.image(it["image"], width=64)
        with col_info:
            meta = []
            if it["price"]:
                meta.append(yen(it["price"]))
            if it["listed_on"]:
                meta.append(f"出品 {it['listed_on']:%Y/%m/%d}")
            m = guess_model(it["name"])
            if m:
                meta.append(f"型番候補: {m}")
            line = f"**{it['name']}**"
            if meta:
                line += "  \n" + " ／ ".join(meta)
            st.markdown(line)
        with col_b1:
            if it["image"]:
                st.link_button("画像でGoogle検索", img_search_url(it["image"]), use_container_width=True)
        with col_b2:
            st.link_button("型番・ブランド名で検索", text_search_url(brand, it["name"]),
                           use_container_width=True)
        st.divider()

    st.caption(
        "※ BUYMAのページ構造が変わると読み取り精度が落ちることがあります。その場合はHTML貼り付けをご利用ください。"
        "ログインが必要なページは扱いません。"
    )


# ============================ 画面：② 複数人まとめてチェック ============================
BULK_MAX_SELLERS = 10


def render_bulk_tool():
    st.title("📋 複数人まとめてチェック")
    st.write("**同じブランドを扱っている出品者を、何人かまとめて比較したいときに使うツールです。**")
    st.caption(
        "各出品者の「ブランドにしぼった新着順一覧ページURL」（① 出品者チェックの②と同じもの）を、"
        f"1行に1人ずつ貼ってください（最大{BULK_MAX_SELLERS}人まで）。"
        "① 出品者チェックより情報は少なめですが、出品総数・出品ペース・直近の動き・拠点国をまとめて比較できます。"
    )

    with st.form("bulk_form"):
        brand_name_bulk = st.text_input("対象ブランド名（表示・候補リスト保存用。任意）", placeholder="例）LOEWE")
        urls_text = st.text_area(
            "出品者ごとの「ブランド一覧（新着順）」URL（1行に1つ）",
            height=150,
            placeholder=(
                "https://www.buyma.com/buyer/1111111/item_1.html\n"
                "https://www.buyma.com/r/-B2222222/\n"
                "…"
            ),
        )
        go3 = st.form_submit_button("まとめてチェックする", type="primary", use_container_width=True)

    if go3:
        all_lines = [u.strip() for u in urls_text.splitlines() if u.strip()]
        urls = all_lines[:BULK_MAX_SELLERS]
        if len(all_lines) > BULK_MAX_SELLERS:
            st.warning(f"URLは最大{BULK_MAX_SELLERS}件までです。上から{BULK_MAX_SELLERS}件だけ処理します。")

        rows = []
        with st.spinner(f"{len(urls)}人分のページを読み込み中…（人数分、時間がかかります）"):
            for u in urls:
                row = {"一覧URL": u}
                try:
                    items, total_count, _, errs = load_listing(u, "", back_pages=2)
                    if not items:
                        row["エラー"] = "商品を読み取れませんでした" + (f"（{errs[0]}）" if errs else "")
                        rows.append(row)
                        continue

                    dated = sorted(it["listed_on"] for it in items if it["listed_on"])
                    oldest = dated[0] if dated else None
                    newest = dated[-1] if dated else None
                    total_disp = total_count or len(items)
                    if oldest and newest and total_disp:
                        pace = (newest - oldest).days / total_disp
                        pace_text = f"平均{pace:.1f}日に1点" if pace >= 0.1 else "ほぼ毎日"
                    else:
                        pace_text = "算出不可"
                    prices = [it["price"] for it in items if it["price"]]
                    median_price = int(statistics.median(prices)) if prices else None

                    seller_id = guess_seller_id(u)
                    name, country, profile_url = None, None, ""
                    if seller_id:
                        profile_url = f"https://www.buyma.com/buyer/{seller_id}.html"
                        prof = load_profile(profile_url, "")
                        name, country = prof.get("name"), prof.get("country")

                    row.update({
                        "出品者名": name or "（不明）",
                        "拠点国": country or "（不明）",
                        "出品総数": total_disp,
                        "扱い始めた日": f"{oldest.year}/{oldest.month}/{oldest.day}" if oldest else "不明",
                        "出品ペース": pace_text,
                        "最終出品からの経過": humanize_since(newest) if newest else "不明",
                        "価格帯の中央値": yen(median_price) if median_price else "不明",
                        "プロフィールURL": profile_url,
                    })
                except Exception as e:  # noqa: BLE001
                    row["エラー"] = f"取得できませんでした（{e}）"
                rows.append(row)

        st.session_state["bulk_result"] = dict(brand_name=brand_name_bulk, rows=rows)

    bres = st.session_state.get("bulk_result")
    if not bres:
        st.info(f"上のフォームにURLを1行に1つずつ貼って（最大{BULK_MAX_SELLERS}人）「まとめてチェックする」を押してください。")
        return

    rows = bres["rows"]
    ok_rows = [r for r in rows if "エラー" not in r]
    err_rows = [r for r in rows if "エラー" in r]

    if ok_rows:
        cols = ["出品者名", "拠点国", "出品総数", "扱い始めた日", "出品ペース",
                "最終出品からの経過", "価格帯の中央値", "一覧URL"]
        st.dataframe(pd.DataFrame(ok_rows)[cols], use_container_width=True, hide_index=True)
        if st.button("⭐ この一覧を候補リストに追加", key="add_watchlist_bulk"):
            for r in ok_rows:
                add_to_watchlist({
                    "追加日時": f"{TODAY.year}/{TODAY.month}/{TODAY.day}",
                    "出品者名": r["出品者名"],
                    "拠点国": r["拠点国"],
                    "ブランド名": bres["brand_name"] or "（未入力）",
                    "出品総数": r["出品総数"],
                    "扱い始めた日": r["扱い始めた日"],
                    "出品ペース": r["出品ペース"],
                    "最終出品からの経過": r["最終出品からの経過"],
                    "一覧URL": r["一覧URL"],
                    "プロフィールURL": r["プロフィールURL"],
                })
            st.success(f"{len(ok_rows)}件を候補リストに追加しました。「⭐ 候補リスト」タブから確認できます。")
    else:
        st.info("読み取れた出品者がいませんでした。")

    for r in err_rows:
        st.warning(f"{r['一覧URL']}：{r['エラー']}")

    st.caption(
        "※ このタブは複数人をすばやく比較するための簡易版です。詳しく調べたい出品者が見つかったら、"
        "「🔎 出品者チェック」タブで改めて詳しく確認することをおすすめします。"
    )


# ============================ 画面：③ 商品ごとの価格チェック ============================
def render_price_tool():
    st.title("💰 商品ごとの価格チェック")
    st.write(
        "**「売れている商品を1つ選んで、その仕入れ先と比べたときに、ちゃんと利益が乗っているか」を確認するツールです。**"
    )
    st.caption(
        "① 調べたい商品のBUYMA商品ページ、② その仕入れ先（海外ショップなど）の商品ページのURLを入れると、"
        "①の実際の販売価格を自動で取得し、②の価格をドル・ユーロ・ポンドなども含めて今のレートで円換算します。"
        "そこに送料・経費を足して、ライバルの実際の利益率と、自分が売る場合の価格の目安を計算します。"
    )

    with st.form("price_check_form"):
        c1, c2 = st.columns(2)
        with c1:
            buyma_url = st.text_input(
                "① 調べたい商品のBUYMA商品ページURL",
                placeholder="https://www.buyma.com/item/12345678/",
            )
        with c2:
            supplier_url = st.text_input(
                "② 仕入れ先の商品ページURL（任意のショップでOK）",
                placeholder="https://www.（仕入れ先のショップ）.com/products/xxxx",
            )
        with st.expander("💡 URLで読み込めないときはHTMLを貼り付け"):
            buyma_html = st.text_area("①のHTML", height=68, key="buyma_html2")
            supplier_html = st.text_area("②のHTML", height=68, key="supplier_html2")
        go2 = st.form_submit_button("価格をチェックする", type="primary", use_container_width=True)

    if go2:
        for k in ("single_buy_price", "os_ship_price", "jp_ship_price"):
            st.session_state.pop(k, None)
        errors = []
        product = {}
        supplier_price = None
        supplier_shipping = None
        with st.spinner("ページを読み込み中…（為替レートの取得も行います）"):
            if buyma_html.strip():
                product = parse_buyma_product(buyma_html)
            elif buyma_url.strip():
                try:
                    product = parse_buyma_product(fetch(buyma_url.strip()))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"①のBUYMA商品ページを取得できませんでした（{e}）。HTML貼り付けをお試しください。")
            else:
                errors.append("①のURL（またはHTML）を入力してください。")

            supplier_html_text = None
            if supplier_html.strip():
                supplier_html_text = supplier_html
            elif supplier_url.strip():
                try:
                    supplier_html_text = fetch(supplier_url.strip())
                except Exception as e:  # noqa: BLE001
                    errors.append(f"②の仕入れ先ページを取得できませんでした（{e}）。仕入れ価格は下で手入力してください。")
            if supplier_html_text:
                supplier_price = extract_price_generic(supplier_html_text)
                supplier_shipping = extract_shipping_hint(supplier_html_text)

            sold_check = None
            if product.get("seller_id") and product.get("item_id"):
                try:
                    sold_check = check_item_sold(product["seller_id"], product["item_id"])
                except Exception:  # noqa: BLE001
                    sold_check = None

        st.session_state["price_result"] = dict(
            product=product, supplier_price=supplier_price, supplier_shipping=supplier_shipping,
            sold_check=sold_check, errors=errors,
        )

    pres = st.session_state.get("price_result")
    if not pres:
        st.info("上のフォームに2つのURLを入れて「価格をチェックする」を押してください。")
        return

    for e in pres["errors"]:
        st.warning(e)

    product = pres["product"]
    if not product.get("price"):
        st.error("①のBUYMA商品ページから価格を読み取れませんでした。URLが商品ページ（/item/…）になっているか確認するか、HTML貼り付けをお試しください。")
        return

    col_img, col_info = st.columns([1, 3])
    with col_img:
        if product.get("image"):
            st.image(product["image"], width=160)
    with col_info:
        st.subheader(product.get("name") or "（商品名を取得できませんでした）")
        if product.get("brand"):
            st.caption(f"ブランド：{product['brand']}")
        st.metric("ライバル（この出品者）の実際の販売価格", yen(product["price"]))

    m1, m2 = st.columns(2)
    listed_on = product.get("listed_on")
    with m1:
        if listed_on:
            m1.metric("この商品の出品日", f"{listed_on.year}年{listed_on.month}月{listed_on.day}日",
                      help="商品画像のURLに埋め込まれた出品日から取得しています。")
        else:
            m1.metric("この商品の出品日", "取得できず")
    with m2:
        sold_check = pres.get("sold_check")
        if not (product.get("seller_id") and product.get("item_id")):
            m2.metric("販売実績への反映", "確認できず")
        elif sold_check is None:
            m2.metric("販売実績への反映", "確認できず")
        elif sold_check["found"]:
            d = sold_check["date"]
            m2.metric("販売実績への反映", f"あり（{d.year}/{d.month}/{d.day}に成約）")
        else:
            m2.metric("販売実績への反映", "まだ見つからず", help=f"出品者の注文実績を直近{sold_check['checked_pages']}ページ確認しました。")
    if listed_on:
        since_listed = (TODAY - listed_on).days
        if since_listed <= 0:
            st.caption("今日出品されたばかりです。")
        else:
            dur_text = humanize_days(since_listed)
            dur_text = dur_text[:-1] if dur_text.endswith("前") else dur_text
            st.caption(f"出品してから{dur_text}経過しています。")
    if pres.get("sold_check") and not pres["sold_check"]["found"]:
        st.caption(
            "※ 注文実績ページ（公開されている分）の中にこの商品IDが見つかりませんでした。"
            "まだ売れていない、実績が非公開、確認したページより前に売れた、のいずれかの可能性があります。"
        )

    # ---- ① 仕入れ価格：外貨を検出できていれば、今の為替レートで円換算した額を初期値にする ----
    default_buy_jpy = 0
    if pres["supplier_price"]:
        amount, currency = pres["supplier_price"]
        fx = fetch_fx_rate(currency) if currency else None
        if fx:
            rate, fx_date = fx
            default_buy_jpy = int(round(amount * rate))
            st.info(
                f"🔎 仕入れ先ページで検出した価格：**{amount:,.2f} {currency}**　"
                f"（為替レート 1 {currency} ＝ ¥{rate:.2f}　{f'{fx_date}時点' if fx_date else ''}）\n\n"
                f"→ 円換算すると **約{yen(default_buy_jpy)}**。下の「仕入れ価格」に自動入力しています"
                "（カード手数料などで多少ずれることがあるので、必要なら書き換えてください）。"
            )
        else:
            st.info(
                f"🔎 仕入れ先ページで検出した価格：**{amount:,.2f} {currency or '（通貨不明）'}**\n\n"
                "為替レートを取得できなかったため、円換算はできませんでした。下に円換算額をご自身で入力してください。"
            )
    else:
        st.caption("仕入れ先ページから価格を自動検出できませんでした（サイトによっては取得できません）。下に実際の仕入れ価格を入力してください。")

    # ---- ② 海外送料：見つかった場合も「参考情報」として見せるだけで、自動入力はしない ----
    # サイトによっては「国内は無料」「$100以上で無料」など、条件付きの送料が複数載っていることが多く、
    # 日本への発送に実際に適用される金額かどうかは自動では判断できないため。
    if pres["supplier_shipping"]:
        parts = []
        for ship_amount, ship_currency in pres["supplier_shipping"][:4]:
            fx2 = fetch_fx_rate(ship_currency) if ship_currency else (1.0, None)
            if fx2:
                parts.append(f"{ship_amount:,.2f} {ship_currency or ''}（約{yen(ship_amount * fx2[0])}）")
            else:
                parts.append(f"{ship_amount:,.2f} {ship_currency or ''}")
        st.caption(
            "🔎 仕入れ先ページに載っていた送料の候補：" + " ／ ".join(parts) + "\n\n"
            "⚠️ 「国内配送のみ無料」「〇〇円以上で無料」など条件付きのことが多く、"
            "日本への発送に実際にいくらかかるかはこの情報だけでは分かりません。"
            "お手数ですが、仕入れ先のサイトで実際の国際配送料をご自身でご確認のうえ、下に入力してください。"
        )

    st.markdown("**原価の内訳（自動入力された金額は書き換えできます）**")
    c1, c2, c3 = st.columns(3)
    with c1:
        buy_price2 = st.number_input(
            "① 仕入れ価格（円）", min_value=0, value=default_buy_jpy, step=1000, key="single_buy_price",
            help="外貨の場合は、円換算した金額を入力してください（自動入力を書き換え可）。",
        )
    with c2:
        os_ship2 = st.number_input(
            "② 海外からの送料（円）", min_value=0, value=0, step=500, key="os_ship_price",
            help="仕入れ先から日本（または転送会社）に届くまでの送料です。サイトで確認した実際の金額を入力してください。",
        )
    with c3:
        jp_ship2 = st.number_input(
            "③ 国内送料・その他経費（円）", min_value=0, value=0, step=500, key="jp_ship_price",
            help="転送会社の手数料、国内発送料、梱包資材代など、そのほかにかかる経費をまとめて入れてください。",
        )

    cost2 = buy_price2 + os_ship2 + jp_ship2
    if cost2 == 0:
        st.info("仕入れ価格を入力すると、利益の目安を計算します。")
        return

    breakeven2 = cost2 / (1 - FEE_RATE)
    actual_price = product["price"]
    net2 = actual_price * (1 - FEE_RATE)
    profit2 = net2 - cost2
    rate2 = profit2 / actual_price if actual_price else 0

    st.divider()
    st.markdown("**① ライバル（この出品者）は、実際どれくらい利益を乗せているか**")
    st.table(pd.DataFrame(
        {"金額": [
            yen(buy_price2), yen(os_ship2), yen(jp_ship2), yen(cost2), yen(breakeven2),
            yen(actual_price), f"−{yen(actual_price * FEE_RATE)}", yen(net2), yen(profit2), f"{rate2 * 100:.1f} %",
        ]},
        index=[
            "仕入れ価格", "海外送料", "国内送料・その他経費", "原価合計",
            "損益分岐売価（これ以下は赤字）", "ライバルの実際の販売価格", "BUYMA手数料（7.7%）",
            "手数料を引いた受取額", "ライバルの実利益", "ライバルの利益率",
        ],
    ))
    if rate2 < 0.15:
        st.error(f"🔴 NG：ライバルの利益率は{rate2 * 100:.1f}%しかありません。")
    elif rate2 < 0.20:
        st.warning(f"🟡 OK：ライバルの利益率は{rate2 * 100:.1f}%です。悪くはありませんが薄めです。")
    else:
        st.success(f"🟢 GOOD：ライバルの利益率は{rate2 * 100:.1f}%です。しっかり利益を確保できています。")

    st.markdown("**② 同じ原価で自分が売るなら、いくらにすればいいか**")
    st.caption("同じ仕入れ価格・送料・経費だった場合に、目標の利益率ごとに必要な販売価格の目安です。")
    target_rates = [0.15, 0.20, 0.25, 0.30]
    target_rows = []
    for r in target_rates:
        denom = 1 - FEE_RATE - r
        price_needed = cost2 / denom if denom > 0 else None
        profit_needed = price_needed * r if price_needed else None
        target_rows.append({
            "目標の利益率": f"{int(r * 100)}%の場合",
            "販売価格の目安": yen(price_needed) if price_needed else "算出不可",
            "見込める利益額": yen(profit_needed) if profit_needed else "—",
        })
    st.table(pd.DataFrame(target_rows).set_index("目標の利益率"))
    st.caption(
        "※ 為替レートは取得できた時点のものです。カード決済時のレートや手数料で実際の金額とは多少ずれます。"
        "関税やBUYMA以外の手数料は含んでいません。"
    )


# ============================ 画面：④ 候補リスト ============================
def render_watchlist_tool():
    st.title("⭐ 候補リスト")
    st.write("**「🔎 出品者チェック」や「📋 複数人まとめてチェック」で気になった出品者を保存しておく場所です。**")
    st.caption(
        "このリストはブラウザを閉じると消えます。あとで見返したいときは、CSVでダウンロードして"
        "Googleスプレッドシートやエクセルに保存してください。"
    )

    wl = st.session_state.get("watchlist") or []
    if not wl:
        st.info(
            "まだ候補リストに追加された出品者がありません。"
            "「🔎 出品者チェック」または「📋 複数人まとめてチェック」の結果画面にある「候補リストに追加」ボタンから追加できます。"
        )
        return

    df = pd.DataFrame(wl)[WATCHLIST_COLUMNS]
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"現在 {len(wl)} 件保存されています。")

    c1, c2 = st.columns(2)
    with c1:
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 CSVでダウンロード（スプレッドシートで開けます）",
            data=csv, file_name="buyma_候補リスト.csv", mime="text/csv",
            use_container_width=True,
        )
    with c2:
        if st.button("🗑 リストを空にする", use_container_width=True):
            st.session_state["watchlist"] = []
            st.rerun()


# ============================ エントリーポイント ============================
def main():
    tab1, tab2, tab3, tab4 = st.tabs([
        "🔎 出品者チェック", "📋 複数人まとめてチェック", "💰 商品ごとの価格チェック", "⭐ 候補リスト",
    ])
    with tab1:
        render_seller_tool()
    with tab2:
        render_bulk_tool()
    with tab3:
        render_price_tool()
    with tab4:
        render_watchlist_tool()


if __name__ == "__main__":
    main()
