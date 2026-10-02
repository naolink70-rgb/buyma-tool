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
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, urljoin, quote_plus, quote

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="BUYMA 出品者チェックツール", page_icon="🛍️", layout="wide")

st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(160deg, #FFF8F5 0%, #FDEDE8 45%, #F7E6F0 100%);
    }
    h1 {
        background: linear-gradient(90deg, #B98AC9, #F2795C);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-weight: 800;
    }
    h2, h3 {
        color: #8B5FA3 !important;
        font-weight: 700;
    }
    h2 {
        border-bottom: 3px solid #F2A98C;
        padding-bottom: 0.3em;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        background-color: #FCE7E2;
        padding: 6px;
        border-radius: 999px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 999px;
        padding: 8px 20px;
        color: #8B5FA3;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(90deg, #F2A98C, #F2795C);
        color: #FFFFFF !important;
    }
    .stTabs [aria-selected="true"] p {
        color: #FFFFFF !important;
    }
    .stButton > button, .stDownloadButton > button {
        border-radius: 999px;
        border: none;
        background: linear-gradient(90deg, #F2A98C, #F2795C);
        color: #FFFFFF;
        font-weight: 600;
        padding: 0.5em 1.6em;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(242, 121, 92, 0.35);
        color: #FFFFFF;
    }
    .stButton > button p, .stDownloadButton > button p {
        color: #FFFFFF !important;
    }
    [data-testid="stCaptionContainer"] {
        opacity: 0.85 !important;
    }
    input::placeholder, textarea::placeholder {
        color: #8A6B63 !important;
        opacity: 1 !important;
    }
    [data-testid="stDataFrame"] canvas[style*="position: absolute"] {
        filter: brightness(0.8) contrast(1.5);
    }
    [data-testid="stForm"], [data-testid="stExpander"] {
        border: 1.5px solid #F0A98C !important;
        border-radius: 14px !important;
        background-color: rgba(255, 255, 255, 0.4) !important;
    }
    /* セレクトボックス・数値入力は、初期状態だと枠線の色が背景色と同じで見分けづらいため、
       はっきりした枠線と白背景を付けて他の背景から浮き立たせる。 */
    [data-testid="stSelectbox"] [data-baseweb="select"] > div,
    [data-testid="stNumberInputContainer"] {
        background-color: #FFFFFF !important;
        border: 1.5px solid #F2795C !important;
        border-radius: 8px !important;
    }
    [data-testid="stRadio"] {
        background-color: rgba(255, 255, 255, 0.5) !important;
        border: 1.5px solid #F0A98C !important;
        border-radius: 10px !important;
        padding: 0.6em 0.8em !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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
    r"(送料無料|国内発送|国内即発|即発送|即納|すぐ届く|在庫あり|正規品|新作|人気|話題|大人気|限定|セール|SALE|"
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
    """② ブランド一覧ページ。新着順の最後の方も数ページさかのぼって最古の出品日を探す。
    戻り値の最後（reached_last_page）は、実際に「最後のページ」まで確認できたかどうか。
    出品数が非常に多い出品者では、そのページ番号がすでに存在しない（削除・変動）ことがあり、
    その場合は False になる ―― 呼び出し側は「扱い始めた日」や「出品ペース」を鵜呑みにしない目安として使う。"""
    if html_text and html_text.strip():
        pr = parse_listing_page(html_text, "https://www.buyma.com/")
        return pr["items"], pr["total_count"], 1, [], True
    if not url or not url.strip():
        return [], None, 1, ["② のURLもHTMLも入力されていません。"], False

    url = url.strip()
    try:
        first = fetch(url)
    except Exception as e:  # noqa: BLE001
        return [], None, 1, [
            f"② ページを取得できませんでした（{e}）。ページを開いて右クリック→"
            "「ページのソースを表示」→全選択コピーして、HTML貼り付け欄に入れてください。"
        ], False

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

    reached_last_page = last_url is None  # 「最後」リンクが無い＝1ページで全件そろっている
    fetched = {url}
    for t in targets:
        if not t or t in fetched:
            continue
        fetched.add(t)
        try:
            items.extend(parse_listing_page(fetch(t), t)["items"])
            if t == last_url:
                reached_last_page = True
        except Exception:  # noqa: BLE001
            pass

    seen, dedup = set(), []
    for it in items:
        k = it["image"].split("?")[0]
        if k in seen:
            continue
        seen.add(k)
        dedup.append(it)
    return dedup, pr["total_count"], last_page, [], reached_last_page


_FEE_ITEM_RE = re.compile(r"(代|料|費)$")


def _is_fee_only_item(name: str) -> bool:
    """「レターパック代」「送料」のような、実商品ではなく送料・手数料を徴収するためだけの
    出品が、注文実績の集計に実商品として紛れ込むのを防ぐ。短く「〜代/料/費」で終わる名前を対象とする。"""
    n = (name or "").strip()
    return bool(n) and len(n) <= 15 and bool(_FEE_ITEM_RE.search(n))


def parse_sales_page(html: str, base_url: str = "https://www.buyma.com/"):
    """注文実績ページから {"date": 販売日, "name": 商品名, "text": カード内の全文,
    "item_id": 商品ID, "image": 商品画像URL, "url": 商品ページURL} のリストを返す。
    ブランド名によるしぼり込みは、name だけでなく text（カード内の見えている文字全部）
    に対しても行う（name の取得に失敗していても text 側でブランド名を拾えることが多いため）。
    image・url は「実際に売れた商品」自体の仕入れ先探しに使う。"""
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
            if d and not _is_fee_only_item(extract_name(card, img)):
                a = card.find("a", href=True)
                idm = re.search(r"/item/(\d+)/", a["href"]) if a else None
                orders.append({
                    "date": d, "name": extract_name(card, img), "text": ctext,
                    "item_id": idm.group(1) if idm else None,
                    "image": img_src(img) or None,
                    "url": urljoin(base_url, a["href"]) if a else None,
                })

    if not orders:  # 画像が拾えないレイアウト向けのフォールバック（商品名・IDは取得できない）
        for m in date_re.finditer(soup.get_text(" ", strip=True)):
            d = to_date(m)
            if d:
                orders.append({"date": d, "name": "", "text": "", "item_id": None, "image": None, "url": None})
    return orders


def order_matches_brand(order: dict, brand: str) -> bool:
    """注文実績の1件が、指定したブランド名を含むか（商品名・カード内テキストの両方を見る）。"""
    if not brand:
        return False
    hay = ((order.get("name") or "") + " " + (order.get("text") or "")).lower()
    return brand.strip().lower() in hay


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


def load_sales(url: str, html_text: str, max_pages: int = 1000):
    """③ 注文実績ページ。sales_1.html → sales_2.html … と自動でめくる。
    BUYMAの注文実績ページは1ページ30件が基本のため、30件未満のページに当たったら
    「本当に最後のページまで読み終えた」とみなす（reached_last_page=True）。
    max_pagesは「無限ループを防ぐための安全装置」であり、通常の出品者数では
    実質上限なしで最後のページまで読み込む（1000ページ＝3万件は現実的には超えない想定）。
    それでも打ち切った場合は reached_last_page=False を返し、
    呼び出し側でその旨を正直に表示できるようにする（高出品数の出品者だと
    「出品開始日」「初めて売れた日」がさかのぼりきれず、実際より新しく見えてしまうため）。"""
    if html_text and html_text.strip():
        return parse_sales_page(html_text), [], True
    if not url or not url.strip():
        return [], ["③ のURLもHTMLも未入力のため、注文実績のチェックはスキップします。"], True

    url = url.strip()
    can_paginate = bool(re.search(r"sales_\d+\.html", url))
    all_orders, errors = [], []
    pages = max_pages if can_paginate else 1
    reached_last_page = True

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
        if len(ords) < 30:  # 1ページ30件に満たない＝本当に最後のページ
            break
        if n == pages and can_paginate:
            reached_last_page = False  # まだ30件フルで、ページ数の上限で打ち切った
    return all_orders, errors, reached_last_page


def extract_country(html: str):
    """プロフィールページに表示されている国旗画像から、出品者の拠点国を取得する。"""
    m = re.search(r'<img[^>]+src="[^"]*flag/[^"]*"[^>]*alt="([^"]+)"', html or "")
    return m.group(1).strip() if m else None


def guess_seller_id(url: str = "", html: str = ""):
    """URLやページ内のリンクから出品者ID（数字）を推測する。
    /buyer/12345.html（プロフィール）、/buyer/12345/...、/r/-B12345.../ のどれにも対応。"""
    for pat in (r"/buyer/(\d+)\.html", r"/buyer/(\d+)/", r"-B(\d+)"):
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
    サイトによっては「国内配送は無料」「$100以上で無料」など複数の条件を同時に載せていることが多いため、
    見つかった候補を (金額, 通貨, 発送先の国コードまたはNone) のリストで全部返す（1つに決め打ちしない）。
    国コードが分かれば「JP（日本）」向けの送料を優先的に案内できる。"""
    found = []
    for node in _iter_jsonld(html):
        for offer in _find_offers(node):
            sd = offer.get("shippingDetails")
            for one in (sd if isinstance(sd, list) else [sd] if sd else []):
                if not isinstance(one, dict):
                    continue
                sr = one.get("shippingRate")
                dest = one.get("shippingDestination")
                dest_list = dest if isinstance(dest, list) else [dest] if dest else []
                country = None
                for d in dest_list:
                    if isinstance(d, dict) and d.get("addressCountry"):
                        country = str(d["addressCountry"]).upper()
                        break
                for r in (sr if isinstance(sr, list) else [sr] if sr else []):
                    if isinstance(r, dict) and r.get("value") is not None:
                        try:
                            val = float(r["value"])
                        except (TypeError, ValueError):
                            continue
                        if val >= 0:
                            pair = (val, (r.get("currency") or "").upper(), country)
                            if pair not in found:
                                found.append(pair)
    return found or None


FREE_SHIP_PATTERNS = [
    re.compile(
        r"free\s+(?:standard\s+|international\s+)?(?:shipping|delivery)[^.\n]{0,40}?"
        r"(?:over|above|on orders? over)\s*([€£$¥])\s*([\d,]+)", re.IGNORECASE,
    ),
    re.compile(r"([€£$¥])\s*([\d,]+)\s*(?:以上)[^.\n]{0,10}(?:送料無料|配送料無料)"),
    re.compile(r"送料無料[^.\n]{0,15}?([€£$¥])\s*([\d,]+)\s*(?:以上)?"),
]
_CURRENCY_SYMBOL_MAP = {"€": "EUR", "£": "GBP", "$": "USD", "¥": "JPY"}


def extract_free_shipping_threshold(html: str):
    """「〇〇円以上で送料無料」のような条件をページの文章から探す（構造化データには無いことが多いため）。
    見つかれば (金額, 通貨) を返す。サイトの言語や書き方次第で見つからないことも多い（参考情報）。"""
    text = soupify(html).get_text(" ", strip=True)
    for pat in FREE_SHIP_PATTERNS:
        m = pat.search(text)
        if m:
            sym, amount_str = m.group(1), m.group(2)
            try:
                amount = float(amount_str.replace(",", ""))
            except ValueError:
                continue
            if amount > 0:
                return amount, _CURRENCY_SYMBOL_MAP.get(sym, "")
    return None


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


@st.cache_data(ttl=1800, show_spinner=False)
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_photo_list(item_url: str):
    """商品ページ本体から、その商品の写真を掲載順ですべて取得する（BUYMAの構造化データから）。
    一覧ページのサムネイル（1枚目）は着用・スタイリングされた「見せ画像」であることが多く、
    画像検索で仕入れ先が見つかりにくいため、2枚目以降の商品単体の写真も選べるようにする。
    取得できなければ空リスト（呼び出し側は1枚目の画像にフォールバックする）。"""
    try:
        html = fetch(item_url)
    except Exception:  # noqa: BLE001
        return []
    for node in _iter_jsonld(html):
        if not isinstance(node, dict) or node.get("@type") not in ("Product", "ProductGroup"):
            continue
        variant = node
        if node.get("@type") == "ProductGroup":
            variants = node.get("hasVariant") or []
            if variants and isinstance(variants[0], dict):
                variant = variants[0]
        img = variant.get("image") if isinstance(variant, dict) else None
        photos = img if isinstance(img, list) else [img] if isinstance(img, str) else []
        if photos:
            return photos
    return []


# ============================ 小さな計算・整形 ============================
def classify(name: str) -> str:
    low = (name or "").lower()
    for cat, kws in CATEGORY_KEYWORDS:
        if any(k in low for k in kws):
            return cat
    return "その他"


# カテゴリー名を英語の検索キーワードに変換する（仕入れ先探しの検索クエリ用）
CATEGORY_EN = {
    "バッグ": "bag",
    "財布・小物": "wallet",
    "靴・スニーカー": "shoes",
    "ワンピース・ドレス": "dress",
    "トップス": "top",
    "アウター": "jacket",
    "ボトムス": "pants",
    "アクセサリー": "accessory",
    "帽子": "hat",
    "ベルト": "belt",
    "マフラー・ストール・スカーフ": "scarf",
    "サングラス・メガネ": "sunglasses",
    "時計": "watch",
    "キーホルダー・チャーム": "keychain",
    "その他": "",
}

# アクセサリーは種類まで分かればより具体的な英語キーワードにする
ACCESSORY_SUBTYPE_EN = [
    (["ネックレス", "necklace", "pendant"], "necklace"),
    (["ブレスレット", "bracelet"], "bracelet"),
    (["ピアス", "イヤリング", "earring"], "earrings"),
    (["リング", "指輪", "ring"], "ring"),
    (["アンクレット", "anklet"], "anklet"),
    (["ブローチ", "brooch"], "brooch"),
]


def category_en(name: str) -> str:
    """商品名からカテゴリーを判定し、検索に使う英語のキーワードを返す。"""
    cat = classify(name)
    low = (name or "").lower()
    if cat == "アクセサリー":
        for kws, en in ACCESSORY_SUBTYPE_EN:
            if any(k in low for k in kws):
                return en
    return CATEGORY_EN.get(cat, "")


def clean_name(name: str) -> str:
    n = re.sub(r"[【】\[\]『』（）()｜|/《》〈〉★☆＿]+", " ", name or "")
    n = DECOR_RE.sub(" ", n)
    n = NOISE_RE.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


_BRAND_STOPWORDS = {
    "MEN'S", "WOMEN'S", "MENS", "WOMENS", "KIDS", "UNISEX",
    "GIRL'S", "BOY'S", "NEW", "SALE", "BUYMA",
}

_KNOWN_BRANDS = [
    "LOUIS VUITTON", "SAINT LAURENT", "BOTTEGA VENETA", "THE NORTH FACE",
    "STONE ISLAND", "CHRISTIAN DIOR", "CHANEL", "HERMES", "HERMÈS", "GUCCI",
    "PRADA", "DIOR", "FENDI", "CELINE", "CÉLINE", "BALENCIAGA", "BURBERRY",
    "MIU MIU", "VALENTINO", "GIVENCHY", "GOYARD", "MONCLER", "LOEWE",
    "COACH", "TORY BURCH", "MICHAEL KORS", "KATE SPADE", "MARC JACOBS",
    "ALEXANDER MCQUEEN", "OFF-WHITE", "AMI PARIS", "JIL SANDER",
    "MACKAGE", "STUSSY", "ADIDAS", "NIKE", "NEW BALANCE", "UGG",
    "STEVE MADDEN", "VERSACE", "GIORGIO ARMANI", "ARMANI",
    "SALVATORE FERRAGAMO", "FERRAGAMO", "TOD'S", "JIMMY CHOO",
    "MANOLO BLAHNIK", "ROGER VIVIER", "CARTIER", "TIFFANY & CO", "TIFFANY",
    "BVLGARI", "MONTBLANC", "ROLEX", "PATEK PHILIPPE", "MAISON MARGIELA",
    "COMME DES GARCONS", "ISSEY MIYAKE", "YOHJI YAMAMOTO", "KENZO",
    "LANVIN", "THOM BROWNE", "RICK OWENS", "VETEMENTS", "BALMAIN",
    "CHLOE", "CHLOÉ", "MULBERRY", "LONGCHAMP", "FURLA", "FEILER",
    "PATAGONIA", "CANADA GOOSE", "BARBOUR", "PURPLE BRAND",
]


def _find_known_brand(text_upper: str) -> str:
    for b in _KNOWN_BRANDS:
        pattern = r"(?<![A-Za-z])" + re.escape(b) + r"(?![A-Za-z])"
        if re.search(pattern, text_upper):
            return b
    return ""


_LATIN_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9&.'\-]*$")
_KATAKANA_TOKEN_RE = re.compile(r"^[ァ-ヴー]+$")
_KATAKANA_STOPWORDS = {
    "スタイル", "デザイン", "サイズ", "カラー", "タイプ", "モデル", "シリーズ",
    "アイテム", "コレクション", "セット", "ポイント", "ランキング", "ブランド",
    "スタッフ", "ページ", "レディース", "メンズ", "キッズ",
    # 商品カテゴリー・素材など、ブランド名ではない一般的な単語
    "バッグ", "シューズ", "ワンピース", "パンツ", "スカート", "ジャケット",
    "コート", "ニット", "セーター", "スニーカー", "サンダル", "ブーツ",
    "パーカー", "ネックレス", "ピアス", "イヤリング", "リング", "ブレスレット",
    "ベルト", "マフラー", "ストール", "キャップ", "ハット", "グローブ",
    "ソックス", "タイツ", "レギンス", "カーディガン", "ブラウス", "シャツ",
    "デニム", "ジーンズ", "スウェット", "フーディー", "ダウン", "レザー",
    "ウール", "コットン", "シルク", "カシミヤ",
    # セール・宣伝でよく出てくる単語
    "セール", "クーポン", "キャンペーン", "プレゼント", "ギフト", "スペシャル",
    "リミテッド", "シーズン", "トレンド", "サマー", "ウィンター",
}


def _looks_brand_like(tok: str, *, allow_katakana: bool = True) -> bool:
    """トークンが「ブランド名っぽいか」を判定する。日本語の宣伝文句（関税・国内発・
    入手困難など）は通常、漢字・ひらがな主体でアルファベットもカタカナ単独でもないため、
    これらを除外することでブランド名らしい単語だけを拾う狙い。"""
    if not tok or tok.upper() in _BRAND_STOPWORDS:
        return False
    if any(c.isdigit() for c in tok):
        return False
    if _LATIN_TOKEN_RE.fullmatch(tok):
        return True
    if allow_katakana and _KATAKANA_TOKEN_RE.fullmatch(tok) and tok not in _KATAKANA_STOPWORDS:
        return True
    return False


def guess_brand_from_name(name: str) -> str:
    """商品名からブランド名を推定する。まず主要ブランドの辞書で商品名全体を検索し、
    見つかればそれを使う（キャッチコピーがブランド名の前に付いていても拾える）。
    辞書に無いブランドは、商品名の先頭付近から「ブランド名っぽい」（英字またはカタカナの）
    単語を探して使う簡易ロジックにフォールバックする（あくまで参考値、精度には限界がある）。
    ブランド名っぽい単語が見つからない場合は空文字を返し、集計対象から除外する。"""
    n = clean_name(name)
    if not n:
        return ""
    known = _find_known_brand(n.upper())
    if known:
        return known
    tokens = [t for t in n.split(" ") if t]
    if not tokens:
        return ""
    start = None
    for i, tok in enumerate(tokens[:6]):
        if _looks_brand_like(tok):
            start = i
            break
    if start is None:
        return ""
    picked = [tokens[start]]
    nxt = start + 1
    if (
        nxt < len(tokens)
        and len(tokens[nxt]) <= 12
        and _looks_brand_like(tokens[nxt], allow_katakana=False)
    ):
        picked.append(tokens[nxt])
    brand = " ".join(picked)
    if len(brand) < 2 or brand.isdigit():
        return ""
    return brand


def brand_group_key(brand: str) -> str:
    """「Custype」と「CUSTYPE」のような大文字・小文字の表記ゆれを1つにまとめて集計するためのキー。"""
    return re.sub(r"\s+", " ", brand.strip()).upper()


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


def buyma_brand_search_url(brand: str) -> str:
    """BUYMA自体のサイト内検索で、そのブランド名の商品一覧を開くリンクを作る。
    ブランドごとの正式な「ブランドページ」のURLはBUYMA内部のコード（カタカナ表記込み）が
    分からないと組み立てられないため、代わりにBUYMAのキーワード検索結果（該当ブランドの
    出品が並ぶページ）にリンクする。BUYMAの検索は `/r/?kw=` ではなく `/r/{キーワード}/` という
    パス形式でないと絞り込みが効かない（`?kw=` は無視され全商品ページが表示されてしまう）ため注意。
    スペースは `+` ではなく `%20` でエンコードする必要がある。"""
    return "https://www.buyma.com/r/" + quote(brand.strip(), safe="") + "/"


def text_search_url(brand: str, name: str) -> str:
    """ブランド名・型番（分かれば）・カテゴリー（英語）を組み合わせた検索クエリを作る。
    型番が取れないときは商品名の一部で代用する。ボタンを押すだけで検索できるように、
    人が手直ししなくてもそれなりの精度になることを狙っている。"""
    model = guess_model(name)
    q = " ".join(x for x in [brand.strip(), model or clean_name(name)[:60], category_en(name)] if x).strip()
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


def format_pace(span_days: int, total_count: int) -> str:
    """出品ペースを分かりやすい文字列にする。
    1点に1日以上かかっているなら「平均X.Y日に1点」、
    1日に複数点出品しているなら「1日に平均X.Y点」という表記にする
    （「平均0.5日に1点」のような分かりにくい数字を避けるため）。"""
    if span_days is None or total_count is None or span_days <= 0 or total_count <= 0:
        return "算出不可"
    days_per_item = span_days / total_count
    if days_per_item >= 1:
        return f"平均 {days_per_item:.1f} 日に1点"
    return f"1日に平均 {total_count / span_days:.1f} 点"


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
    "追加日時", "出品者名", "拠点国", "ブランド名", "ブランドページURL", "出品総数",
    "扱い始めた日", "初めて売れた日", "出品ペース", "最終出品からの経過", "一覧URL", "プロフィールURL",
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


def render_sourcing_row(it: dict, brand: str):
    """商品1件ぶんの「仕入れ先を探す」行を描画する（出品中の商品にも、実際に売れた商品にも使う）。"""
    photos = fetch_photo_list(it["url"]) if it.get("url") else []
    options = photos[1:4] if len(photos) > 1 else []  # 1枚目（見せ画像）は除く

    col_img, col_info = st.columns([1, 5])
    with col_img:
        if it.get("image"):
            st.image(it["image"], width=64)
    with col_info:
        meta = []
        if it.get("price"):
            meta.append(yen(it["price"]))
        if it.get("listed_on"):
            meta.append(f"出品 {it['listed_on']:%Y/%m/%d}")
        if it.get("sold_on"):
            meta.append(f"成約 {it['sold_on']:%Y/%m/%d}")
        m = guess_model(it.get("name") or "")
        if m:
            meta.append(f"型番候補: {m}")
        line = f"**{it.get('name') or '（商品名不明）'}**"
        if meta:
            line += "  \n" + " ／ ".join(meta)
        st.markdown(line)

    if options:
        st.caption("👇 編集されていなさそうな写真を選んでGoogle画像検索")
        photo_cols = st.columns(len(options))
        for photo_col, photo_url in zip(photo_cols, options):
            with photo_col:
                st.image(photo_url, width=100)
                st.link_button("この写真で検索", img_search_url(photo_url), use_container_width=True)
    elif it.get("image"):
        st.link_button("画像でGoogle検索", img_search_url(it["image"]), use_container_width=True)

    st.link_button("型番・ブランド名・カテゴリーで検索", text_search_url(brand, it.get("name") or ""),
                   use_container_width=True)
    st.divider()


# ============================ 画面：① 出品者チェック ============================
def render_seller_tool():
    st.title("🛍️ BUYMA 出品者チェックツール")
    st.write(
        "気になる出品者のページURLを貼るだけで、**そのブランドをどれくらい動かしているか / "
        "売れているか / 相場**をまとめて確認します。"
    )
    st.caption("💰 利益が出せそうかを調べたいときは「商品ごとの価格チェック」タブをお使いください。")

    with st.expander("使い方（クリックで開く）"):
        st.markdown("**① プロフィールのリンクを貼る**（これだけは必須）")
        st.markdown("**② ブランドで絞った新着ページのリンクを貼る**（空欄でもOK）")
        st.markdown("**③ 注文実績ページのリンクを貼る**（空欄でもOK・①から自動で探します）")
        st.write("")
        st.markdown("②が空欄のときは、その出品者の**全ブランド合計**の数字になります。")
        st.markdown("特定のブランドだけを見たいときは、②に「ブランドで絞り込み→新着順」にしたページのリンクを貼ってください。")
        st.write("")
        st.markdown("貼り終わったら「チェックする」を押すだけです。")
        st.write("")
        st.caption("※ ブランド全体の競合出品者数は、ブランドページでご自身で確認してください（このツールでは扱いません）。")

    # 履歴は、①〜③を貼り付けるフォームより上に表示する
    # （途中でデータが消えても、URLを1から貼り直す前にまず履歴を確認できるように）
    history = st.session_state.get("seller_history", [])
    if history:
        labels = [
            f"{h['profile'].get('name') or '（出品者名不明）'}｜{h['brand_name'] or '（ブランド未入力）'}｜{h['checked_at']} 時点"
            for h in history
        ]
        st.selectbox(
            "📜 チェック履歴（このブラウザを閉じるまでの分だけ、新しい順）",
            range(len(labels)), format_func=lambda i: labels[i], key="seller_history_select",
        )
        st.caption("※ ブラウザを閉じたり、しばらく操作しないとこの履歴は消えます。あとで見返したい結果は「候補リストに追加」してCSVで保存してください。")
        st.divider()

    with st.form("inputs"):
        c1, c2 = st.columns(2)
        with c1:
            profile_url = st.text_input(
                "① 出品者プロフィールページのURL（これだけは必須）",
                placeholder="https://www.buyma.com/buyer/0000000.html",
            )
            brand_url = st.text_input(
                "② 対象ブランドにしぼった「新着順」一覧ページのURL（空欄でもOK）",
                placeholder="空欄なら①から出品者の全商品一覧を自動で見ます（全ブランド合計になります）",
                help="ブランドで絞り込み→並び替えを新着順にしたページのURLです。空欄の場合、その出品者の全ブランド合計の数字になります。",
            )
        with c2:
            sales_url = st.text_input(
                "③ 注文実績ページのURL（空欄でもOK）",
                placeholder="空欄なら①から自動で見つけます",
                help="空欄の場合、①のプロフィールURLから自動で注文実績ページを探します。",
            )
            brand_name = st.text_input("対象ブランド名（仕入れ先さがしの検索に使います）", placeholder="例）LOEWE")
        with st.expander("💡 URLで読み込めないとき（Community Cloud でブロックされる場合など）はHTMLを貼り付け"):
            st.caption("各ページをブラウザで開き、右クリック →「ページのソースを表示」→ 全選択してコピー → ここに貼り付け。")
            profile_html = st.text_area("① プロフィールページのHTML", height=68)
            brand_html = st.text_area("② ブランド一覧ページのHTML", height=68)
            sales_html = st.text_area("③ 注文実績ページのHTML", height=68)
        go = st.form_submit_button("チェックする", type="primary", use_container_width=True)

    if go:
        # ①だけでもチェックできるように、②③が空欄なら①から出品者IDを推測して自動で組み立てる
        seller_id = guess_seller_id(profile_url.strip()) if profile_url.strip() else None
        if not seller_id and profile_html.strip():
            seller_id = guess_seller_id("", profile_html)

        auto_brand_url = False
        if not brand_url.strip() and not brand_html.strip() and seller_id:
            brand_url = f"https://www.buyma.com/buyer/{seller_id}/item_1.html"
            auto_brand_url = True
        if not sales_url.strip() and not sales_html.strip() and seller_id:
            sales_url = f"https://www.buyma.com/buyer/{seller_id}/sales_1.html"

        with st.spinner(
            "BUYMAのページを読み込み中…（注文実績は最後のページまで読み込みます。"
            "出品数・注文実績が多い出品者ほど時間がかかり、数分かかることがあります）"
        ):
            items, total_count, last_page, e1, reached_last_page = load_listing(brand_url, brand_html)
            orders, e2, sales_reached_last_page = load_sales(sales_url, sales_html)
            profile = load_profile(profile_url, profile_html)
        now = dt.datetime.now()
        new_result = dict(
            items=items, total_count=total_count, last_page=last_page, reached_last_page=reached_last_page,
            orders=sorted(orders, key=lambda o: o["date"]), sales_reached_last_page=sales_reached_last_page,
            profile=profile, brand_name=brand_name,
            profile_url=profile_url.strip(), brand_url=brand_url.strip(), auto_brand_url=auto_brand_url,
            errors=[m for m in (*e1, *e2) if m],
            checked_at=f"{now.month}/{now.day} {now.hour:02d}:{now.minute:02d}",
        )
        history = st.session_state.setdefault("seller_history", [])
        history.insert(0, new_result)
        del history[10:]  # 直近10件だけ残す（増えすぎ防止）
        st.session_state.pop("seller_history_select", None)  # 一番新しい結果を選び直す
        st.rerun()  # 上の履歴プルダウンに今の結果をすぐ反映させる

    history = st.session_state.get("seller_history", [])
    if not history:
        st.info("上のフォームに3つのURLを入れて「チェックする」を押してください。")
        return

    idx = st.session_state.get("seller_history_select", 0)
    res = history[idx]

    items = res["items"]
    orders = res["orders"]
    sales_reached_last_page = res.get("sales_reached_last_page", True)
    typed_brand = (res["brand_name"] or "").strip()

    # ②のURLで出品一覧はすでにブランド絞り込み済みなのに、「対象ブランド名」欄が空欄・不一致だと
    # 注文実績（商品名でのテキスト一致）側だけ絞り込めない、というズレを防ぐ。
    # ②が手入力されていれば、出品一覧の商品名から一番多いブランド名を推定し、それでも注文実績を絞り込む。
    inferred_brand = None
    if not res.get("auto_brand_url") and items:
        guesses = Counter(guess_brand_from_name(it.get("name") or "") for it in items)
        guesses.pop("", None)
        if guesses:
            inferred_brand = guesses.most_common(1)[0][0]

    brand = typed_brand
    brand_orders = [o for o in orders if typed_brand and order_matches_brand(o, typed_brand)]
    brand_is_inferred = False
    if not brand_orders and inferred_brand:
        alt_orders = [o for o in orders if order_matches_brand(o, inferred_brand)]
        if alt_orders:
            brand_orders = alt_orders
            brand = inferred_brand
            brand_is_inferred = True

    # ブランド名で絞り込めていればそちらを、できていなければ全件を「関係ありそうな注文」として扱う。
    # 候補リストへの追加ボタン（1.）、仕入れ先探し（4.）の両方で使う。
    relevant_orders = brand_orders if (brand and brand_orders) else orders
    first_sale_date = min((o["date"] for o in relevant_orders), default=None)

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
    if res.get("auto_brand_url"):
        st.warning(
            "⚠️ ②のURLが未入力だったため、この出品者の**全ブランド合計**の一覧を自動で見ています。"
            "特定のブランドだけに絞り込みたい場合は、②にブランド絞り込み後のURLを入力してください。"
        )

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

    reached_last_page = res.get("reached_last_page", True)
    if oldest and newest and total_disp and reached_last_page:
        pace_text = format_pace((newest - oldest).days, total_disp)
    else:
        pace_text = "算出不可" if reached_last_page else "算出不可（最後のページを確認できず）"
        if not reached_last_page:
            oldest = None

    since = (TODAY - newest).days if newest else None

    status_rows = [
        ("このブランドの出品総数", f"{total_disp:,} 点"),
        ("このブランドを扱い始めた日", f"{oldest.year}年{oldest.month}月{oldest.day}日" if oldest else "取得できず"),
        ("出品ペース", pace_text),
        ("最後の出品から", humanize_since(newest) if newest else "取得できず"),
    ]

    st.table(pd.DataFrame(status_rows, columns=["項目", "値"]).set_index("項目"))

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

    if brand_is_inferred and brand_orders:
        use_orders = brand_orders
        st.info(
            f"🔎「対象ブランド名」が未入力（または注文実績に見当たらない）でしたが、②の一覧から"
            f"**「{brand}」**と推定して注文実績を絞り込みました（{len(brand_orders)}件 / "
            f"全ブランド合計{len(orders)}件中）。"
        )
    elif brand and brand_orders:
        use_orders = brand_orders
        st.info(
            f"🔎「{brand}」を含む注文にしぼり込んで表示しています（{len(brand_orders)}件 / "
            f"全ブランド合計{len(orders)}件中）。"
        )
    elif typed_brand and orders:
        use_orders = orders
        st.warning(
            f"⚠️「{typed_brand}」を含む注文は見つかりませんでした。**まだこのブランドが売れていない可能性**があります。"
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
        if not is_brand_specific:
            # ブランドを絞り込めていないと、「出品開始日」と「初めて売れた日」が別々の商品のものになり、
            # 比較しても意味のある数字にならないため、この場合は計算そのものをしない。
            lag = None
            a.metric("出品開始 → 初めて売れるまで", "対象外")
            a.caption("ブランドを絞り込むと計算します（今は色々な商品の日付が混ざっているため）。")
        elif oldest:
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

        if not sales_reached_last_page:
            st.warning(
                f"⚠️ 注文実績が多いため、直近{len(orders)}件（{first_sale:%Y/%m}〜{last_sale:%Y/%m}）までしか"
                "確認できていません。それより前の注文実績は含まれていないため、"
                "「出品開始 → 初めて売れるまで」「確認できた販売件数」「月あたりの平均販売数」は、"
                "実際より新しく・少なく出ている可能性があります。"
            )

        if lag is not None and lag < 0:
            st.caption(
                "※ このブランドの出品開始日より前の日付の注文が見つかったため、初回販売までの日数は計算していません"
                "（出品日をさかのぼりきれていない可能性があります）。"
            )

        if is_brand_specific:
            st.markdown("**月ごとの数字（新しい月が上）**")
            all_months = sorted(set(listing_months) | set(months), reverse=True)
            month_table = pd.DataFrame({
                "日付": [jp_month(k) for k in all_months],
                "ブランド名": [brand] * len(all_months),
                "出品数": [listing_monthly.get(k, 0) for k in all_months],
                "販売数": [monthly.get(k, 0) for k in all_months],
            })
            st.table(month_table.set_index("日付"))
        else:
            st.caption(
                "💡 特定ブランドの絞り込みができていないため、この下の「よく売れているブランド」ランキングと"
                "「上位ブランドの月間販売数」の表で、ブランドごとの内訳を確認してください。"
            )

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
        st.divider()
        st.subheader("📊 この出品者の「よく売れているブランド」ランキング（推定）")
        st.caption(
            "出品一覧・注文実績それぞれの商品名の先頭の単語からブランドを推定して集計しています。"
            "③のURLは入力不要です（①だけ入力していれば、自動取得した注文実績を使います）。"
        )

        # 大文字・小文字の表記ゆれ（Custype / CUSTYPE など）を1つのブランドとして数えるため、
        # 集計は正規化したキーで行い、表示には最初に見つかった表記をそのまま使う。
        listing_brand_counts = Counter()
        for it in items:
            b = guess_brand_from_name(it.get("name") or "")
            if b:
                listing_brand_counts[brand_group_key(b)] += 1

        sold_brand_counts = Counter()
        brand_display = {}
        last_sold_on = {}
        unknown = 0
        for o in orders:
            b = guess_brand_from_name(o.get("name") or "")
            if b:
                key = brand_group_key(b)
                sold_brand_counts[key] += 1
                brand_display.setdefault(key, b)
                if key not in last_sold_on or o["date"] > last_sold_on[key]:
                    last_sold_on[key] = o["date"]
            else:
                unknown += 1

        if not sold_brand_counts:
            st.info("商品名を取得できた注文が少なく、ブランドごとの集計を作成できませんでした。")
        else:
            rank_rows = []
            for rank, (key, total) in enumerate(sold_brand_counts.most_common(10), start=1):
                b = brand_display[key]
                since_sold = (TODAY - last_sold_on[key]).days
                if since_sold <= 30:
                    trend = "🔥 直近も売れています"
                elif since_sold <= 90:
                    trend = "🙂 たまに動いています"
                else:
                    trend = f"⚠️ 最近は売れていません（{humanize_days(since_sold)}）"
                rank_rows.append({
                    "順位": f"{rank}位",
                    "ブランド（推定）": b,
                    "ブランドページ": buyma_brand_search_url(b),
                    "出品数（確認できた範囲）": listing_brand_counts.get(key, 0),
                    "総販売数": total,
                    "直近の動き": trend,
                })
            st.dataframe(
                pd.DataFrame(rank_rows).set_index("順位"),
                use_container_width=True,
                column_config={
                    "ブランドページ": st.column_config.LinkColumn("ブランドページ", display_text="🔗 開く"),
                },
            )
            st.caption(
                f"確認できた注文実績{len(orders)}件のうち、商品名からブランド名を推定できた"
                f"{sum(sold_brand_counts.values())}件を集計しています（{unknown}件は商品名を取得できず対象外）。"
                "商品名からブランド名っぽい単語を探す簡易的な推定のため、精度には限界があります。"
                "「ブランドページ」はBUYMA内のキーワード検索結果を開くリンクのため、"
                "うまくブランド名を推定できていない行では関係のないページが開くことがあります。"
                "「出品数」は取得できた出品一覧の範囲での点数（出品数が多い出品者では実際より少なく出ることがあります）、"
                "「総販売数」は確認できた注文実績の中での件数です"
                + ("（注文実績が多いため直近分のみで、古い実績は含まれていません）。" if not sales_reached_last_page else "。")
            )

            # ランキング上位ブランドについて、月ごとの販売数も見られるように
            bm_counts = Counter()
            for o in orders:
                b = guess_brand_from_name(o.get("name") or "")
                if b:
                    bm_counts[(brand_group_key(b), month_key(o["date"]))] += 1
            all_dates = [o["date"] for o in orders]
            month_list = month_span(min(all_dates), max(all_dates))[-12:]

            st.markdown("**上位ブランドの月間販売数**（直近12ヶ月、新しい月が右）")
            top_keys = [key for key, _ in sold_brand_counts.most_common(10)]
            pivot_rows = []
            for key in top_keys:
                row = {"ブランド（推定）": brand_display[key]}
                for mk in month_list:
                    row[jp_month(mk)] = bm_counts.get((key, mk), 0)
                row["合計"] = sold_brand_counts[key]
                pivot_rows.append(row)
            st.dataframe(
                pd.DataFrame(pivot_rows).set_index("ブランド（推定）"),
                use_container_width=True,
            )

    st.write("")
    with st.container(key="watchlist_add_container"):
        st.markdown(
            """
            <style>
            .st-key-watchlist_add_container button {
                background-color: #8B5FA3;
                color: #FFFFFF !important;
                border: 1px solid #8B5FA3;
                border-radius: 999px;
                padding: 0.5em 1.6em;
                font-weight: 600;
            }
            .st-key-watchlist_add_container button:hover {
                background-color: #714B87;
                border-color: #714B87;
                color: #FFFFFF !important;
            }
            .st-key-watchlist_add_container button p {
                color: #FFFFFF !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        add_clicked = st.button("⭐ 候補リストに追加", key="add_watchlist_seller")
    if add_clicked:
        add_to_watchlist({
            "追加日時": f"{TODAY.year}/{TODAY.month}/{TODAY.day}",
            "出品者名": res["profile"].get("name") or "（不明）",
            "拠点国": res["profile"].get("country") or "（不明）",
            "ブランド名": brand or "（未入力）",
            "ブランドページURL": buyma_brand_search_url(brand) if brand else "",
            "出品総数": total_disp,
            "扱い始めた日": f"{oldest.year}/{oldest.month}/{oldest.day}" if oldest else "不明",
            "初めて売れた日": (
                f"{first_sale_date.year}/{first_sale_date.month}/{first_sale_date.day}"
                if first_sale_date else "不明（実績なし・非公開）"
            ),
            "出品ペース": pace_text,
            "最終出品からの経過": humanize_since(newest) if newest else "不明",
            "一覧URL": res.get("brand_url") or "",
            "プロフィールURL": res.get("profile_url") or "",
        })
        st.success("候補リストに追加しました。「📒 ブランド候補リスト」タブから確認・ダウンロードできます。")

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
    LIMIT = 24

    # 実際に売れた商品（注文実績から、item_idが分かるもののみ・重複は除く）
    sold_items, seen_ids = [], set()
    for o in relevant_orders:
        if not o.get("item_id") or o["item_id"] in seen_ids or not (o.get("image") and o.get("url")):
            continue
        seen_ids.add(o["item_id"])
        sold_items.append({
            "name": o.get("name") or "（商品名不明）", "image": o["image"], "url": o["url"],
            "price": None, "listed_on": None, "sold_on": o["date"],
        })
    sold_items.sort(key=lambda x: x["sold_on"], reverse=True)

    if sold_items:
        st.subheader("✅ 実際に売れた商品から探す（おすすめ）")
        st.caption("すでに売れた実績がある商品です。仕入れ先を探す優先度が高いのはこちらです。")
        with st.spinner("売れた商品の写真を確認しています…"):
            for it in sold_items[:LIMIT]:
                render_sourcing_row(it, brand)
        if len(sold_items) > LIMIT:
            st.caption(f"※ 売れた商品が多いため、新しい方から{LIMIT}件を表示しています。")
        st.divider()
    else:
        st.info(
            "注文実績の中から、今の出品一覧と突き合わせられる「売れた商品」が見つかりませんでした"
            "（売り切れて出品一覧から消えている場合や、注文実績が非公開の場合があります）。"
            "下の「出品中の商品」から探してください。"
        )

    st.subheader("📦 出品中の商品から探す")
    shown = items[:LIMIT]
    if len(items) > LIMIT:
        st.caption(f"※ 商品が多いため、新しい方から{LIMIT}件を表示しています。")
    st.caption(
        "💡 一覧の1枚目は着用・スタイリングされた「見せ画像」で、画像検索がヒットしにくいことがあります。"
        "下に商品単体の写真をいくつか並べるので、編集されていなさそうな写真を選んで検索してください。"
    )

    with st.spinner("各商品の写真を確認しています…"):
        for it in shown:
            render_sourcing_row(it, brand)

    st.caption(
        "※ BUYMAのページ構造が変わると読み取り精度が落ちることがあります。その場合はHTML貼り付けをご利用ください。"
        "ログインが必要なページは扱いません。"
    )


# ============================ 画面：② 商品ごとの価格チェック ============================
# 関税率の目安（2026年4月1日時点、税関の公式ページ2本をもとに作成）：
#   - 一般税率（商用輸入・個人輸入どちらにも使える正式な税率）
#     https://www.customs.go.jp/tetsuzuki/c-answer/imtsukan/1204_jr.htm （主な商品の関税率の目安）
#   - 簡易税率（課税価格20万円以下の個人輸入だけに使える簡易な税率。
#     革製バッグ・ニット製衣類・履物は対象外で、個人輸入でも一般税率を使うことになっている）
#     https://www.customs.go.jp/tsukan/kanizeiritsu.htm （少額輸入貨物の簡易税率）
# 実際の税率は素材・原産国・加工の有無などで変わるため、ここでの数字は目安（レンジの中間値）。
_DUTY_CATEGORIES = {
    "選択してください": None,
    "皮バッグ（ハンドバッグ等）": {
        "personal": 12.0, "commercial": 12.0,
        "note": "革製バッグは簡易税率の対象外のため、個人輸入でも一般税率（目安8〜16%、中間値12%）になります。",
    },
    "フェイクレザー（合成皮革バッグ等）": {
        "personal": 12.0, "commercial": 12.0,
        "note": (
            "合成皮革・PVC素材のバッグも、本革製バッグと同じ関税分類（ハンドバッグとして同じ税率区分）"
            "になるため、税率は本革と同じ目安8〜16%（中間値12%）です。"
        ),
    },
    "革靴（レザーシューズ）": {
        "personal": 30.0, "commercial": 30.0,
        "note": (
            "靴も簡易税率の対象外です。一般税率は「30%」または「1足あたり4,300円」の高い方になるため、"
            "価格が安いほど実質の税率は上がります。安価な商品は、この%欄だけでは正確に出ないことがあるので、"
            "通関手数料欄も使って手動で調整してください。"
        ),
    },
    "Tシャツ": {
        "personal": 9.0, "commercial": 9.0,
        "note": (
            "綿・ポリエステルなど素材に関わらず、Tシャツの生地は「メリヤス編み＝引っ張ると伸びる生地」"
            "に分類されるため（セーターと同じ区分）、簡易税率の対象外です。一般税率の目安は7.4〜10.9%（中間値9%）。"
        ),
    },
    "アウター（織物・毛皮以外）": {
        "personal": 10.0, "commercial": 10.6,
        "note": (
            "織物素材のコート・ジャケットを想定。個人輸入（課税価格20万円以下）なら簡易税率10%、"
            "商用輸入は一般税率の目安8.4〜12.8%（中間値10.6%）。セーターなどニット素材の場合は、"
            "個人輸入でも簡易税率の対象外になるため商用と同じ一般税率を使ってください。"
        ),
    },
    "ジャケット": {
        "personal": 10.0, "commercial": 10.6,
        "note": "アウターと同じ区分（繊維製のコート・ジャケット類）のため、税率も同じです。ニット素材の場合は商用と同じ一般税率になります。",
    },
    "ジャンバー（ブルゾン等）": {
        "personal": 10.0, "commercial": 10.6,
        "note": "アウターと同じ区分（繊維製のコート・ジャケット類）のため、税率も同じです。ニット素材の場合は商用と同じ一般税率になります。",
    },
    "ウールコート": {
        "personal": 10.0, "commercial": 10.6,
        "note": "毛皮ではなくウール生地のコートを想定。アウターと同じ区分のため税率も同じです（毛皮コートは下の「ファーアウター」を選んでください）。",
    },
    "ファーアウター（毛皮）": {
        "personal": 20.0, "commercial": 20.0,
        "note": "毛皮製品は簡易税率・一般税率のどちらも20%です。",
    },
    "ボトムス（パンツ・スカート/織物）": {
        "personal": 10.0, "commercial": 10.6,
        "note": (
            "織物素材のパンツ・スカートを想定。個人輸入（課税価格20万円以下）なら簡易税率10%、"
            "商用輸入は一般税率の目安8.4〜12.8%（中間値10.6%）。"
        ),
    },
    "ニット（セーター等）": {
        "personal": 10.6, "commercial": 10.6,
        "note": (
            "セーター・カーディガンなどのニット（メリヤス編み）製品は簡易税率の対象外。"
            "個人輸入・商用輸入どちらも一般税率の目安8.4〜12.8%（中間値10.6%）になります。"
        ),
    },
    "スウェット": {
        "personal": 10.6, "commercial": 10.6,
        "note": (
            "スウェット（トレーナー）もニットと同じ編み物生地のため簡易税率の対象外。"
            "個人輸入・商用輸入どちらも一般税率の目安8.4〜12.8%（中間値10.6%）になります。"
        ),
    },
    "マフラー（スカーフ類）": {
        "personal": 10.0, "commercial": 6.8,
        "note": (
            "織物素材のマフラー・スカーフを想定。個人輸入（課税価格20万円以下）は簡易税率10%、"
            "商用輸入は一般税率の目安4.4〜9.1%（中間値6.8%）。ニット編みのマフラーの場合は、"
            "個人輸入でも簡易税率の対象外になるため商用と同じ一般税率を使ってください。"
        ),
    },
    "アクセサリー（貴金属・宝石）": {
        "personal": 5.0, "commercial": 5.3,
        "note": (
            "金・銀・プラチナ・貴石製のアクセサリーを想定。商用輸入は一般税率の目安5.2〜5.4%（中間値5.3%）、"
            "個人輸入（課税価格20万円以下）は簡易税率の「その他のもの」区分5%を目安にしています。"
            "メッキなど貴金属以外の素材（コスチュームジュエリー）は税率が異なることがあります。"
        ),
    },
}


def _apply_duty_category():
    """カテゴリー・個人/商用の選択に応じて、関税率欄の数字を書き換える（selectbox/radioのon_change用）。"""
    cat = _DUTY_CATEGORIES.get(st.session_state.get("duty_category"))
    if not cat:
        return
    mode = "personal" if st.session_state.get("duty_mode") == "個人輸入" else "commercial"
    st.session_state["duty_rate_pct"] = cat[mode]


# 通関手数料の目安（配送会社によって課税方式が大きく違う）：
#   - 日本郵便（EMS・国際郵便）：関税等を着払いで徴収する際の取扱手数料は郵便物1個につき200円
#     https://www.customs.go.jp/tetsuzuki/c-answer/kokusaiyubin/6101_jr.htm
#   - DHL：立替納税手数料は「2,530円」または「立替額（関税＋消費税）の2%」の高い方（アカウント請求の場合）
#   - FedEx：立替手数料（ADVC）は従来1,000円。2026年7月に改定されており、最新額は要確認
_CLEARANCE_CARRIERS = {
    "選択してください": None,
    "日本郵便（EMS・国際郵便）": {"type": "fixed", "value": 200,
                           "note": "関税等を着払いで徴収する際の取扱手数料は、郵便物1個につき200円です。"},
    "DHL": {"type": "dhl", "min": 2530, "rate": 0.02,
            "note": "立替納税手数料は「2,530円」または「関税・消費税の立替額の2%」の高い方です（アカウント請求の場合）。"},
    "FedEx": {"type": "fixed", "value": 1000,
              "note": "立替手数料（ADVC）の目安は1,000円ですが、2026年7月に料金改定があったため最新額はFedEx公式サイトでご確認ください。"},
}


def _apply_clearance_fee():
    """配送会社の選択に応じて、通関手数料欄の数字を書き換える（selectboxのon_change用）。
    DHLは「立替額（関税＋消費税）の2%」が絡むため、関税率・課税価格をsession_stateから読み直して計算する。"""
    carrier = _CLEARANCE_CARRIERS.get(st.session_state.get("clearance_carrier"))
    if not carrier:
        return
    if carrier["type"] == "fixed":
        st.session_state["clearance_fee"] = carrier["value"]
    elif carrier["type"] == "dhl":
        buy = st.session_state.get("single_buy_price", 0) or 0
        ship = st.session_state.get("os_ship_price", 0) or 0
        mode_rate = 0.6 if st.session_state.get("duty_mode") == "個人輸入" else 1.0
        taxable = int(((buy + ship) * mode_rate) // 1000) * 1000  # 課税価格は1,000円未満切り捨て
        duty_rate = (st.session_state.get("duty_rate_pct", 0) or 0) / 100
        duty = int((taxable * duty_rate) // 100) * 100  # 関税額は100円未満切り捨て
        tax = (taxable + duty) * 0.10
        st.session_state["clearance_fee"] = int(round(max(carrier["min"], (duty + tax) * carrier["rate"])))


# 国内配送方法の目安料金：
#   クリックポスト・レターパック系は2026年10月1日の日本郵便料金改定後の金額
#   https://jobdonebot.com/blog/japan-post-price-hike-2026-10-guide
#   かんたんBUYMA便（匿名配送）はBUYMA・日本郵便間の料金表の実際の金額（ユーザー確認済み）
_DOMESTIC_SHIP_METHODS = {
    "選択してください": None,
    "クリックポスト": 240,
    "レターパックライト": 430,
    "レターパックプラス": 600,
    "かんたんBUYMA便【匿名配送】-ゆうパケット": 280,
    "かんたんBUYMA便【匿名配送】-ゆうパック 60サイズ": 800,
    "かんたんBUYMA便【匿名配送】-ゆうパック 80サイズ": 950,
    "かんたんBUYMA便【匿名配送】-ゆうパック 100サイズ": 1100,
    "かんたんBUYMA便【匿名配送】-ゆうパック 120サイズ": 1250,
}


def _apply_domestic_ship():
    """配送方法の選択に応じて、国内送料欄の数字を書き換える（selectboxのon_change用）。"""
    value = _DOMESTIC_SHIP_METHODS.get(st.session_state.get("domestic_ship_method"))
    if value is not None:
        st.session_state["jp_ship_price"] = value


def render_price_tool():
    st.title("💰 商品ごとの価格チェック")
    st.write(
        "**「売れている商品を1つ選んで、その仕入れ先と比べたときに、ちゃんと利益が乗っているか」を確認するツールです。**"
    )
    with st.expander("使い方（クリックで開く）"):
        st.markdown("**① 調べたい商品のBUYMA商品ページのリンクを貼る**")
        st.markdown("**② その仕入れ先（海外ショップなど）の商品ページのリンクを貼る**")
        st.write("")
        st.markdown("①の実際の販売価格を自動で取得します。")
        st.markdown("②の価格は、ドル・ユーロ・ポンドなども含めて今のレートで円換算します。")
        st.markdown("そこに送料・経費を足して、ライバルの実際の利益率と、自分が売る場合の価格の目安を計算します。")

    # 履歴は、①②を貼り付けるフォームより上に表示する
    history2 = st.session_state.get("price_history", [])
    if history2:
        labels2 = [
            f"{h['product'].get('name') or '（商品名不明）'}｜{h['checked_at']} 時点"
            for h in history2
        ]
        st.selectbox(
            "📜 チェック履歴（このブラウザを閉じるまでの分だけ、新しい順）",
            range(len(labels2)), format_func=lambda i: labels2[i], key="price_history_select",
        )
        st.caption("※ ブラウザを閉じたり、しばらく操作しないとこの履歴は消えます。")
        st.divider()

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
            free_ship_threshold = None
            if supplier_html_text:
                supplier_price = extract_price_generic(supplier_html_text)
                supplier_shipping = extract_shipping_hint(supplier_html_text)
                free_ship_threshold = extract_free_shipping_threshold(supplier_html_text)

            sold_check = None
            if product.get("seller_id") and product.get("item_id"):
                try:
                    sold_check = check_item_sold(product["seller_id"], product["item_id"])
                except Exception:  # noqa: BLE001
                    sold_check = None

        now = dt.datetime.now()
        new_pres = dict(
            product=product, supplier_price=supplier_price, supplier_shipping=supplier_shipping,
            free_ship_threshold=free_ship_threshold, sold_check=sold_check, errors=errors,
            checked_at=f"{now.month}/{now.day} {now.hour:02d}:{now.minute:02d}",
        )
        history2 = st.session_state.setdefault("price_history", [])
        history2.insert(0, new_pres)
        del history2[10:]
        st.session_state.pop("price_history_select", None)
        st.rerun()  # 上の履歴プルダウンに今の結果をすぐ反映させる

    history2 = st.session_state.get("price_history", [])
    if not history2:
        st.info("上のフォームに2つのURLを入れて「価格をチェックする」を押してください。")
        return

    idx2 = st.session_state.get("price_history_select", 0)
    pres = history2[idx2]

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
    # サイトによっては複数の発送先ごとに送料を分けて載せていることがあり、そのときは国コードから
    # 「日本(JP)向け」を優先して案内する。日本向けが見当たらない場合は、他の発送先の送料だけを参考に見せる。
    def _fmt_ship(v, c):
        fx2 = fetch_fx_rate(c) if c else (1.0, None)
        return f"{v:,.2f} {c or ''}（約{yen(v * fx2[0])}）" if fx2 else f"{v:,.2f} {c or ''}"

    shipping = pres.get("supplier_shipping")
    if shipping:
        jp_rates = [s for s in shipping if s[2] in ("JP", "JAPAN")]
        other_rates = [s for s in shipping if s[2] not in ("JP", "JAPAN")]
        if jp_rates:
            parts = [_fmt_ship(v, c) for v, c, _ in jp_rates[:3]]
            st.info("🔎 日本への送料として見つかった金額：" + " ／ ".join(parts))
        else:
            parts = [
                f"{_fmt_ship(v, c)}{f'（{d}向け）' if d else ''}" for v, c, d in other_rates[:3]
            ]
            st.warning(
                "⚠️ **日本への配送情報が見つかりません。** ページに載っていたのは次の送料でした："
                + " ／ ".join(parts)
                + "\n\nこのショップが日本へ発送しているか、サイトでご確認ください。"
            )
        st.caption(
            "※ 「国内配送のみ無料」など条件付きのことも多く、自動検出はあくまで参考です。"
            "実際の国際配送料は仕入れ先のサイトでご確認のうえ、下に入力してください。"
        )
    else:
        st.caption("仕入れ先ページから送料の情報は見つけられませんでした。サイトでご確認のうえ、下に入力してください。")

    free_ship = pres.get("free_ship_threshold")
    if free_ship:
        fs_amount, fs_currency = free_ship
        fx3 = fetch_fx_rate(fs_currency) if fs_currency else (1.0, None)
        yen_text = f"（約{yen(fs_amount * fx3[0])}）" if fx3 else ""
        st.caption(f"💡 「{fs_amount:,.2f} {fs_currency or ''}{yen_text} 以上で送料無料」という記載がページ内に見つかりました。")

    st.markdown("**原価の内訳（自動入力された金額は書き換えできます）**")
    c1, c2 = st.columns(2)
    with c1:
        buy_price2 = st.number_input(
            "① 仕入れ価格＝商品代金（円）", min_value=0, value=default_buy_jpy, step=1000, key="single_buy_price",
            help="外貨の場合は、円換算した金額を入力してください（自動入力を書き換え可）。",
        )
    with c2:
        os_ship2 = st.number_input(
            "② 海外からの送料＝国際送料（円）", min_value=0, value=0, step=500, key="os_ship_price",
            help="仕入れ先から日本（または転送会社）に届くまでの送料です。サイトで確認した実際の金額を入力してください。",
        )

    st.markdown("**③ 関税・消費税を計算する**")

    cat1, cat2 = st.columns(2)
    with cat1:
        st.radio(
            "個人輸入・商用輸入", ["個人輸入", "商用輸入"], key="duty_mode", horizontal=True,
            on_change=_apply_duty_category,
            help=(
                "個人輸入：自分で使う目的の輸入で使える計算方法。課税価格＝（商品代金＋送料）×60%。\n"
                "商用輸入：転売・事業目的の輸入で使う計算方法。課税価格＝（商品代金＋送料）×100%（割引なし）。\n\n"
                "※ 0.6倍ルールについて：税関の「少額輸入貨物の簡易税率」ページには今も0.6倍ルールが"
                "記載されていますが、このページは2025年5月更新のままで、2026年4月の関税定率法改正"
                "（令和8年法律第5号、同日施行）が反映されていない可能性があります。改正後の扱いは"
                "ページによって記載が食い違っているため、不安な場合は税関相談官に確認してください。"
            ),
        )
    with cat2:
        st.selectbox(
            "商品カテゴリーから関税率を入れる（任意）",
            list(_DUTY_CATEGORIES.keys()), key="duty_category", on_change=_apply_duty_category,
            help="選ぶと下の「関税率（%）」に目安の数字が自動で入ります。入力後も自由に書き換えられます。",
        )
    selected_cat = _DUTY_CATEGORIES.get(st.session_state.get("duty_category"))
    if selected_cat:
        st.caption(f"💡 {selected_cat['note']}")

    duty_mode_rate = 0.6 if st.session_state.get("duty_mode") == "個人輸入" else 1.0
    taxable_value2_raw = (buy_price2 + os_ship2) * duty_mode_rate
    taxable_value2 = int(taxable_value2_raw // 1000) * 1000  # 課税価格は1,000円未満切り捨て
    if st.session_state.get("duty_mode") == "個人輸入":
        st.caption(f"課税価格 ＝（商品代金＋送料）×60% ＝ {yen(taxable_value2)}（1,000円未満切り捨て）")
    else:
        st.caption(f"課税価格 ＝（商品代金＋送料）×100% ＝ {yen(taxable_value2)}（1,000円未満切り捨て）")

    cc1, cc2 = st.columns(2)
    with cc1:
        duty_rate_pct = st.number_input(
            "関税率（%）", min_value=0.0, max_value=50.0, value=0.0, step=0.5, key="duty_rate_pct",
            help=(
                "上のカテゴリーを選ぶと自動入力されますが、正確な税率は商品ごとに違うため、"
                "分かる場合はここを書き換えてください。\n\n"
                "課税価格1万円以下は原則免税ですが、かばん類・ニット製衣類・靴などは金額に関わらず"
                "免税の対象外です（BUYMAで扱う商品の多くが該当するため要注意）。\n\n"
                "さらに2028年4月からは、1万円以下の消費税免税が廃止され、大手プラットフォーム経由の"
                "輸入には消費税の納税義務が課される予定です。個人輸入の税優遇は今後さらに縮小していく見込みです。"
            ),
        )
    with cc2:
        st.selectbox(
            "通関業者（配送会社）から通関手数料を入れる（任意）",
            list(_CLEARANCE_CARRIERS.keys()), key="clearance_carrier", on_change=_apply_clearance_fee,
            help="選ぶと下の「通関手数料」に目安の数字が自動で入ります。入力後も自由に書き換えられます。",
        )
        selected_carrier = _CLEARANCE_CARRIERS.get(st.session_state.get("clearance_carrier"))
        if selected_carrier:
            st.caption(f"💡 {selected_carrier['note']}")
        clearance_fee2 = st.number_input(
            "通関手数料（円・任意）", min_value=0, value=0, step=100, key="clearance_fee",
            help="利用する配送会社・転送会社によって発生する通関手数料です（無ければ0のままでOK）。",
        )
    duty2_raw = taxable_value2 * (duty_rate_pct / 100)
    duty2 = int(duty2_raw // 100) * 100  # 関税額は100円未満切り捨て
    consumption_tax2 = (taxable_value2 + duty2) * 0.10
    customs2 = duty2 + consumption_tax2 + clearance_fee2
    if duty_rate_pct > 0:
        st.caption(
            f"課税価格 {yen(taxable_value2)} → 関税 {yen(duty2)} ＋ 消費税 {yen(consumption_tax2)} "
            f"＋ 通関手数料 {yen(clearance_fee2)} ＝ **関税・消費税の合計 {yen(customs2)}**"
        )
    else:
        st.caption("関税率を入力すると、ここに関税・消費税の合計が表示されます（0%のままなら0円として計算します）。")

    st.markdown("**④ 国内送料・その他経費**")
    st.selectbox(
        "配送方法から国内送料を入れる（任意）",
        list(_DOMESTIC_SHIP_METHODS.keys()), key="domestic_ship_method", on_change=_apply_domestic_ship,
        help=(
            "お客様に発送するときの国内配送方法です。選ぶと下の金額欄に自動で入ります。"
            "「かんたんBUYMA便」は、BUYMAと日本郵便が連携した匿名配送サービスです"
            "（ゆうパケット・ゆうパックのサイズ別料金）。実際のサイズは商品によって変わるため、"
            "選んだあとも金額欄は自由に書き換えてください。"
        ),
    )
    jp_ship2 = st.number_input(
        "国内送料・その他経費（円）", min_value=0, value=0, step=500, key="jp_ship_price",
        help="転送会社の手数料、国内発送料、梱包資材代など、そのほかにかかる経費をまとめて入れてください。",
    )

    cost2 = buy_price2 + os_ship2 + customs2 + jp_ship2
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
            yen(buy_price2), yen(os_ship2), yen(customs2), yen(jp_ship2), yen(cost2), yen(breakeven2),
            yen(actual_price), f"−{yen(actual_price * FEE_RATE)}", yen(net2), yen(profit2), f"{rate2 * 100:.1f} %",
        ]},
        index=[
            "仕入れ価格", "海外送料", "関税・消費税", "国内送料・その他経費", "原価合計",
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
    target_rates = [r / 100 for r in range(15, 71, 5)]  # 15%〜70%まで5%刻み
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
        "関税・消費税は「①仕入れ価格＋②海外送料」を課税価格とみなし、上で入力した関税率をもとに自動計算しています。"
        "関税率そのものはカテゴリーごとに異なるため手入力です。それ以外のBUYMA以外の手数料は含んでいません。"
    )
    st.info(
        "💡 **関税の目安について**：2026年4月1日に制度が変わりました。以前は「課税価格＝海外価格×0.6」"
        "だったため約1万6,666円までが実質免税でしたが、この0.6倍の特例が廃止され、"
        "今は海外価格＋送料（CIF価格）がそのまま課税価格になります。"
        "**課税価格が1万円以下**なら原則として関税・消費税が免除されます。"
        "ただし**かばん類・ニット製衣類・靴などは、金額に関わらずこの免税の対象外**です。"
        "BUYMAで扱う商品はこれらのカテゴリーが多いため、免税になると思い込まないようご注意ください。"
        "目安として、関税（カテゴリーにより8〜16%程度）＋消費税10%で、"
        "合計は価格のだいたい20〜25%程度になることが多いです。"
        "最新のルールは[税関のサイト](https://www.customs.go.jp/tsukan/kanizeiritsu.htm)でご確認ください。"
    )


# ============================ 画面：③ 候補リスト ============================
def render_watchlist_tool():
    st.title("📒 ブランド候補リスト")
    st.write("**「🔎 出品者チェック」で気になった出品者を保存しておく場所です。**")
    st.caption("このリストはブラウザを閉じると消えます。")
    st.caption("あとで見返したいときは、CSVでダウンロードしてGoogleスプレッドシートやエクセルに保存してください。")

    wl = st.session_state.get("watchlist") or []
    if not wl:
        st.info(
            "まだ候補リストに追加された出品者がありません。"
            "「🔎 出品者チェック」の結果画面にある「候補リストに追加」ボタンから追加できます。"
        )
        return

    df = pd.DataFrame(wl)[WATCHLIST_COLUMNS]
    st.dataframe(
        df, use_container_width=True, hide_index=True,
        column_config={
            "ブランドページURL": st.column_config.LinkColumn("ブランドページ", display_text="🔗 開く"),
            "一覧URL": st.column_config.LinkColumn("一覧URL", display_text="🔗 開く"),
            "プロフィールURL": st.column_config.LinkColumn("プロフィールURL", display_text="🔗 開く"),
        },
    )
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
    tab1, tab2, tab3 = st.tabs([
        "🔎 出品者チェック", "💰 商品ごとの価格チェック", "📒 ブランド候補リスト",
    ])
    with tab1:
        render_seller_tool()
    with tab2:
        render_price_tool()
    with tab3:
        render_watchlist_tool()


if __name__ == "__main__":
    main()
