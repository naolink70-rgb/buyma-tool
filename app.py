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
from concurrent.futures import ThreadPoolExecutor
import threading
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, urljoin, quote_plus, quote

import pandas as pd
import requests
import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
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
    [data-testid="stMultiSelect"] [data-baseweb="select"] > div,
    [data-testid="stNumberInputContainer"],
    [data-testid="stTextInput"] [data-baseweb="input"],
    [data-testid="stTextInput"] [data-baseweb="base-input"],
    [data-testid="stTextArea"] [data-baseweb="textarea"],
    [data-testid="stTextArea"] [data-baseweb="base-input"] {
        background-color: #FFFFFF !important;
        border: 2px solid #E8664A !important;
        border-radius: 8px !important;
    }
    /* 文字を入れる欄（URLなどを貼る場所）は、中の入力部分も白にして、貼った文字を濃く見せる */
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stNumberInput"] input {
        background-color: #FFFFFF !important;
        color: #2B1F1B !important;
    }
    [data-testid="stTextInput"] input::placeholder,
    [data-testid="stTextArea"] textarea::placeholder {
        color: #A89690 !important;
    }
    [data-testid="stTextInput"] [data-baseweb="input"]:focus-within,
    [data-testid="stTextArea"] [data-baseweb="textarea"]:focus-within {
        border-color: #C2410C !important;
        box-shadow: 0 0 0 3px rgba(242, 121, 92, 0.25) !important;
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


def _gender_from_breadcrumb(html: str) -> str:
    """商品ページのパンくず（BreadcrumbList）から「メンズ」「レディース」「キッズ」を読み取る。"""
    for blob in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html or "", re.S):
        try:
            d = json.loads(blob)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict) and d.get("@type") == "BreadcrumbList":
            for it in d.get("itemListElement", []):
                n = it.get("name") or (it.get("item") or {}).get("name") or ""
                if n.startswith("メンズ"):
                    return "メンズ"
                if n.startswith("レディース"):
                    return "レディース"
                if n.startswith("ベビー") or n.startswith("キッズ"):
                    return "キッズ"
    return "不明"


def _gender_from_name(name: str) -> str:
    """商品ページを見られなかった（出品終了など）ときの代わりに、商品名の「Men's」「Women's」などから推定する。"""
    n = name or ""
    if re.search(r"レディース|ウィメンズ|ウーマン|\bwomen'?s?\b|\bwomens\b|\bladies\b|\bwmns\b", n, re.I):
        return "レディース"
    if re.search(r"メンズ|\bmen'?s?\b|\bmens\b", n, re.I):
        return "メンズ"
    return "不明"


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_item_genders(item_ids: tuple) -> dict:
    """売れた商品のIDから、商品ページのカテゴリー（メンズ／レディース）をまとめて調べる。出品終了で見られないものは「不明」。"""
    def one(i):
        try:
            r = requests.get(f"https://www.buyma.com/item/{i}/", headers=HEADERS, timeout=15)
            return i, (_gender_from_breadcrumb(r.text) if r.status_code == 200 else "不明")
        except Exception:  # noqa: BLE001
            return i, "不明"
    with ThreadPoolExecutor(max_workers=8) as ex:
        return dict(ex.map(one, item_ids))


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
    # 色・サイズ・仕様など、ブランド名ではない英単語
    "BLACK", "WHITE", "GREEN", "BLUE", "RED", "GRAY", "GREY", "NAVY", "BEIGE", "BROWN", "PINK",
    "YELLOW", "ORANGE", "PURPLE", "KHAKI", "IVORY", "SILVER", "GOLD", "CREAM", "OLIVE", "CAMEL",
    "BURGUNDY", "WINE", "MINT", "LIME", "TAN", "CHARCOAL", "MULTI", "BLK", "WHT", "GRY", "NVY",
    "FREE", "SIZE", "SET", "LIMITED", "JAPAN", "KOREA", "WOMEN", "MEN", "LOGO", "BASIC",
    "SMALL", "MEDIUM", "LARGE", "ONE", "NEW",
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


# 商品名にカタカナや別表記で書かれているブランド名を、正式なブランド名に直すための対応表。
# （カタカナは「・」とスペースを除いた形で照合する）
_BRAND_ALIASES = {
    "ザノースフェイス": "THE NORTH FACE", "ノースフェイス": "THE NORTH FACE",
    "NORTH FACE": "THE NORTH FACE", "TNF": "THE NORTH FACE",
    "ステューシー": "STUSSY", "ナイキ": "NIKE", "アディダス": "ADIDAS",
    "ニューバランス": "NEW BALANCE", "シュプリーム": "SUPREME", "パタゴニア": "PATAGONIA",
    "ヴァンズ": "VANS", "バンズ": "VANS", "コンバース": "CONVERSE",
    "ラルフローレン": "RALPH LAUREN", "カナダグース": "CANADA GOOSE",
    "シャネル": "CHANEL", "エルメス": "HERMES", "ルイヴィトン": "LOUIS VUITTON",
    "グッチ": "GUCCI", "プラダ": "PRADA", "ディオール": "DIOR", "フェンディ": "FENDI",
    "セリーヌ": "CELINE", "バレンシアガ": "BALENCIAGA", "バーバリー": "BURBERRY",
    "ミュウミュウ": "MIU MIU", "ヴァレンティノ": "VALENTINO", "バレンティノ": "VALENTINO",
    "ジバンシィ": "GIVENCHY", "ジバンシー": "GIVENCHY", "ゴヤール": "GOYARD",
    "モンクレール": "MONCLER", "ロエベ": "LOEWE", "コーチ": "COACH", "アグ": "UGG",
    "ストーンアイランド": "STONE ISLAND", "ジルサンダー": "JIL SANDER",
}


def _find_known_brand(text_upper: str) -> str:
    kata = text_upper.replace("・", "").replace(" ", "").replace("　", "")
    for alias, canonical in _BRAND_ALIASES.items():
        if re.fullmatch(r"[A-Z ]+", alias):
            if re.search(r"(?<![A-Za-z])" + re.escape(alias) + r"(?![A-Za-z])", text_upper):
                return canonical
        elif alias in kata:
            return canonical
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
    # 素材・形・色・装飾など、ブランド名ではない一般的なカタカナ
    "ナイロン", "ポリエステル", "フリース", "ボア", "ロゴ", "ダウン", "ジャージ", "ウェア",
    "ロング", "ショート", "ハーフ", "ミニ", "ビッグ", "オーバーサイズ", "スリム", "ワイド",
    "ホワイト", "ブラック", "ネイビー", "グレー", "グリーン", "ブルー", "レッド", "ベージュ",
    "ブラウン", "ピンク", "イエロー", "オレンジ", "パープル", "カーキ", "アイボリー", "シルバー",
    "ゴールド", "ベーシック", "カジュアル", "オリジナル", "レディース", "メンズ", "ユニセックス",
    "フード", "ジップ", "ポケット", "ボタン", "プリント", "ストライプ", "チェック", "ライン",
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
        return len(tok) >= 3
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


def _watchlist_key(row: dict) -> tuple:
    """候補リストで「同じもの」と判定するための組み合わせ。同じ出品者でもブランドが違えば別の行として保存する。"""
    return (
        row.get("プロフィールURL") or row.get("一覧URL") or row.get("出品者名") or "",
        (row.get("ブランド名") or "").strip().lower(),
        row.get("一覧URL") or "",
    )


def add_to_watchlist(row: dict):
    """候補リスト（st.session_state）に1行追加する。出品者・ブランド・一覧URLがすべて同じものが既にあれば上書きする。"""
    wl = st.session_state.setdefault("watchlist", [])
    key = _watchlist_key(row)
    for i, existing in enumerate(wl):
        if _watchlist_key(existing) == key:
            wl[i] = row
            return
    wl.append(row)


def import_watchlist_csv(uploaded) -> int:
    """前回ダウンロードした候補リストのCSVを読み込み、今のリストに合流させる。読み込んだ行数を返す。"""
    df = pd.read_csv(uploaded, encoding="utf-8-sig").fillna("")
    count = 0
    for rec in df.to_dict("records"):
        if not rec.get("出品者名") and not rec.get("プロフィールURL"):
            continue  # スプレッドシートに貼り付けた際に混ざった空行・ヘッダー行などは飛ばす
        if rec.get("追加日時") == "追加日時":
            continue
        add_to_watchlist({c: rec.get(c, "") for c in WATCHLIST_COLUMNS})
        count += 1
    return count


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
_GCOL = {  # 見出しの色：(背景, 文字, 本文のうすい色)
    "total": ("#FFE8D1", "#C2410C", "#FFF8F0"),
    "men": ("#DBEAFE", "#1D4ED8", "#F3F8FF"),
    "women": ("#FCE7F3", "#BE185D", "#FFF3F9"),
    "unknown": ("#EDEDF0", "#4B5563", "#F8F8FA"),
    "plain": ("#F6E3DC", "#6B4A40", "#FFFFFF"),
}


def gender_cards_html(items: list) -> str:
    """合計・メンズ・レディースなどを、同じ大きさの色つきカードで並べる。items=[(ラベル, 数字, 色キー)]"""
    import html as _h
    cards = ""
    for label, val, key in items:
        bg, fg, tint = _GCOL[key]
        cards += (
            f'<div style="flex:1 1 0;min-width:0;border:1.5px solid {fg}33;border-radius:12px;background:{tint};padding:10px 12px;">'
            f'<div style="display:inline-block;background:{bg};color:{fg};font-weight:700;font-size:0.85rem;padding:2px 10px;border-radius:999px;">{_h.escape(label)}</div>'
            f'<div style="font-size:1.9rem;font-weight:600;color:#4A3B36;margin-top:4px;">{val:,}<span style="font-size:1rem;"> 件</span></div></div>'
        )
    return f'<div style="display:flex;gap:10px;margin:6px 0 14px 0;">{cards}</div>'


def gender_table_html(columns: list, rows: list) -> str:
    """列の幅をそろえた、見出しに色つきの表。columns=[(列名, 色キー, 幅%)]"""
    import html as _h
    cg = "".join(f'<col style="width:{w}%">' for _, _, w in columns)
    th = "".join(
        f'<th style="background:{_GCOL[k][0]};color:{_GCOL[k][1]};padding:8px 6px;text-align:center;font-weight:700;border:1px solid #F0A98C55;">{_h.escape(n)}</th>'
        for n, k, _ in columns
    )
    body = ""
    for r in rows:
        tds = ""
        for (n, k, _), v in zip(columns, r):
            tds += (
                f'<td style="background:{_GCOL[k][2]};padding:6px;text-align:center;border:1px solid #F0A98C33;'
                f'color:{"#B5A39C" if v == 0 else "#4A3B36"};">{_h.escape(str(v))}</td>'
            )
        body += f"<tr>{tds}</tr>"
    return (
        f'<table style="width:100%;table-layout:fixed;border-collapse:collapse;border-radius:10px;overflow:hidden;">'
        f"<colgroup>{cg}</colgroup><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"
    )


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

    is_brand_specific = use_orders is brand_orders
    _all_orders_g, _g = None, None
    if use_orders and is_brand_specific:
        _all_orders_g = list(use_orders)  # 性別の内訳（合計・メンズ・レディース）は、絞り込む前の全件で数える
        with st.spinner("売れた商品のメンズ／レディースを調べています…（初回だけ少し時間がかかります）"):
            genders = fetch_item_genders(tuple(sorted({o["item_id"] for o in use_orders if o.get("item_id")})))

        def _g(o):
            g = genders.get(o.get("item_id"), "不明")
            return g if g != "不明" else _gender_from_name(o.get("name") or "")

        gender_pick = st.radio(
            "性別（メンズ／レディース）で絞り込む", ["すべて", "メンズ", "レディース"], key="order_gender", horizontal=True,
            help=(
                "注文実績のページ自体にはメンズ・レディースの区別がないため、売れた商品1つ1つの商品ページを調べて分類しています。"
                "すでに出品が終わった商品は商品ページが見られないので、商品名の「Men's」「Women's」などから判断し、"
                "それでも分からないものは絞り込み時に除かれます。"
            ),
        )
        if gender_pick != "すべて":
            total_before = len(use_orders)
            unknown_n = sum(1 for o in use_orders if _g(o) == "不明")
            use_orders = [o for o in use_orders if _g(o) == gender_pick]
            relevant_orders = use_orders  # 下の「実際に売れた商品」の一覧も、同じ性別にしぼる
            st.caption(
                f"「{gender_pick}」の注文実績にしぼり込んでいます（{len(use_orders)}件 / このブランド全体{total_before}件中）。"
                f"男女を判別できなかった{unknown_n}件（出品終了で商品ページが見られず、商品名にも手がかりがないもの）は含まれていません。"
                "なお、下の月ごとの表の「出品数」は、性別では絞り込まれません。"
            )

    if not use_orders:
        st.info("公開されている注文実績が見つかりませんでした。実績がまだ少ない出品者か、注文実績を公開していない可能性があります。"
                "（性別で絞り込んでいる場合は、「すべて」に戻すと表示されることがあります）")
    else:
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
            if _all_orders_g and _g:
                gc = Counter(_g(o) for o in _all_orders_g)
                st.markdown("**売れた件数の内訳（注文実績）**")
                st.markdown(
                    gender_cards_html([
                        ("合計", len(_all_orders_g), "total"),
                        ("メンズ", gc.get("メンズ", 0), "men"),
                        ("レディース", gc.get("レディース", 0), "women"),
                        ("判別できず", len(_all_orders_g) - gc.get("メンズ", 0) - gc.get("レディース", 0), "unknown"),
                    ]),
                    unsafe_allow_html=True,
                )
            st.markdown("**月ごとの数字（新しい月が上）**")
            all_months = sorted(set(listing_months) | set(months), reverse=True)
            tbl = {
                "日付": [jp_month(k) for k in all_months],
                "ブランド名": [brand] * len(all_months),
                "出品数": [listing_monthly.get(k, 0) for k in all_months],
                "販売数": [monthly.get(k, 0) for k in all_months],
            }
            if _all_orders_g and _g:
                by_m = {}
                for o in _all_orders_g:
                    by_m.setdefault(month_key(o["date"]), Counter())[_g(o)] += 1
                tbl["販売数（メンズ）"] = [by_m.get(k, Counter()).get("メンズ", 0) for k in all_months]
                tbl["販売数（レディース）"] = [by_m.get(k, Counter()).get("レディース", 0) for k in all_months]
                tbl["判別できず"] = [
                    sum(v for kk, v in by_m.get(k, Counter()).items() if kk not in ("メンズ", "レディース")) for k in all_months
                ]
            if "販売数（メンズ）" in tbl:
                cols_def = [("日付", "plain", 13), ("ブランド名", "plain", 17), ("出品数", "plain", 14), ("販売合計", "total", 14),
                            ("メンズ販売", "men", 14), ("レディース販売", "women", 14), ("判別できず", "unknown", 14)]
                keys = ["日付", "ブランド名", "出品数", "販売数", "販売数（メンズ）", "販売数（レディース）", "判別できず"]
                st.markdown(
                    gender_table_html(cols_def, [[tbl[k][i] for k in keys] for i in range(len(tbl["日付"]))]),
                    unsafe_allow_html=True,
                )
            else:
                st.table(pd.DataFrame(tbl).set_index("日付"))
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
        st.success(
            f"候補リストに追加しました（現在 {len(st.session_state['watchlist'])} 件）。"
            "「📒 ブランド候補リスト」タブでCSVをダウンロードして保存してください。"
            "ブラウザを閉じるとリストは消えます。"
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
    LIMIT = 24

    # 実際に売れた商品（注文実績から、item_idが分かるもののみ・重複は除く）
    sold_items, seen_ids = [], set()
    for o in relevant_orders:
        if not o.get("item_id") or o["item_id"] in seen_ids or not (o.get("image") and o.get("url")):
            continue
        seen_ids.add(o["item_id"])
        sold_items.append({
            "name": o.get("name") or "（商品名不明）", "image": o["image"], "url": o["url"],
            "price": None, "listed_on": None, "sold_on": o["date"], "item_id": o["item_id"],
        })
    sold_items.sort(key=lambda x: x["sold_on"], reverse=True)

    if sold_items:
        st.subheader("✅ 実際に売れた商品から探す（おすすめ）")
        _gp = st.session_state.get("order_gender", "すべて")
        st.caption(
            "すでに売れた実績がある商品です。仕入れ先を探す優先度が高いのはこちらです。"
            + (f"（上の「{_gp}」の絞り込みが反映されています）" if _gp != "すべて" else "　商品名の前の【メンズ】【レディース】は、商品ページから判定しています。")
        )
        _gmap = fetch_item_genders(tuple(it["item_id"] for it in sold_items[:LIMIT]))
        for it in sold_items[:LIMIT]:
            g = _gmap.get(it["item_id"], "不明")
            if g == "不明":
                g = _gender_from_name(it["name"])
            if g in ("メンズ", "レディース"):
                it["name"] = f"【{g}】{it['name']}"
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
    # 関税率が未入力（0%）かつカテゴリー未選択のときは、関税・消費税は計算しない（通関手数料だけ入力されていればそれのみ加算）
    calc_customs = duty_rate_pct > 0 or selected_cat is not None
    if calc_customs:
        duty2_raw = taxable_value2 * (duty_rate_pct / 100)
        duty2 = int(duty2_raw // 100) * 100  # 関税額は100円未満切り捨て
        consumption_tax2 = (taxable_value2 + duty2) * 0.10
    else:
        duty2 = 0
        consumption_tax2 = 0
    customs2 = duty2 + consumption_tax2 + clearance_fee2
    if calc_customs:
        st.caption(
            f"課税価格 {yen(taxable_value2)} → 関税 {yen(duty2)} ＋ 消費税 {yen(consumption_tax2)} "
            f"＋ 通関手数料 {yen(clearance_fee2)} ＝ **関税・消費税の合計 {yen(customs2)}**"
        )
    else:
        st.caption(
            "関税・消費税は計算していません（0円）。計算するには、商品カテゴリーを選ぶか関税率を入力してください。"
            f"通関手数料のみ入力した場合は {yen(clearance_fee2)} が加算されます。"
        )

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
    st.warning(
        "このリストは**ブラウザを閉じる・しばらく放置すると消えます**。"
        "毎回、下の「CSVでダウンロード」で保存してください。"
        "後日あらためて追加するときは、先に「前回のCSVを読み込む」で前回の分を戻すと、続きから溜められます。"
    )

    with st.expander("📂 前回のCSVを読み込む（続きから追加したいとき）", expanded=not st.session_state.get("watchlist")):
        uploaded = st.file_uploader("前回ダウンロードした「buyma_候補リスト.csv」を選んでください", type="csv", key="watchlist_upload")
        if uploaded is not None:
            done = st.session_state.setdefault("watchlist_imported_ids", [])
            if uploaded.file_id not in done:
                try:
                    n = import_watchlist_csv(uploaded)
                    done.append(uploaded.file_id)
                    st.success(f"{n}件を読み込みました。")
                except Exception as e:  # noqa: BLE001
                    st.error(f"CSVを読み込めませんでした（{e}）。ダウンロードしたCSVをそのまま選んでください。")

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


# ============================ 画面：③ 仕入れ先リサーチ ============================
SOURCING_COLUMNS = [
    "交渉済み", "追加日時", "BUYMA商品名", "BUYMA売価", "仕入れ先サイト", "種類", "仕入れ先商品名",
    "現地価格", "通貨", "円換算", "VAT表示", "VAT率", "VAT根拠", "在庫（サイズ別）", "電話", "メール", "問い合わせページ",
    "仕入れ先URL", "BUYMA商品URL", "メモ", "リンク集", "ショップ情報",
]

# 各国のGoogleの窓口（ドメイン, 言語, 国コード）。検索結果は、その国向けの表示になる。
_SEARCH_COUNTRIES = {
    "🇺🇸 アメリカ": ("google.com", "en", "US"),
    "🇬🇧 イギリス": ("google.co.uk", "en", "GB"),
    "🇮🇹 イタリア": ("google.it", "it", "IT"),
    "🇫🇷 フランス": ("google.fr", "fr", "FR"),
    "🇩🇪 ドイツ": ("google.de", "de", "DE"),
    "🇪🇸 スペイン": ("google.es", "es", "ES"),
    "🇰🇷 韓国": ("google.co.kr", "ko", "KR"),
    "🇦🇺 オーストラリア": ("google.com.au", "en", "AU"),
    "🇨🇦 カナダ": ("google.ca", "en", "CA"),
    "🇯🇵 日本": ("google.co.jp", "ja", "JP"),
}

_JP_CHARS_RE = re.compile(r"[぀-ヿ一-鿿＀-￯・]+")
_CONTACT_WORDS = (
    "contact", "support", "customer", "help", "faq", "service-client", "kontakt", "contatti",
    "contacto", "お問い合わせ", "お問合せ", "問い合わせ", "문의",
)
_MODEL_STOP_RE = re.compile(r"^(?:20\d{2}(?:ss|aw|fw|pf)?|\d{1,3}(?:cm|mm|g|kg|ml|l)|w\d{2}|h\d{2})$", re.I)


def guess_model_candidates(*texts: str, limit: int = 8) -> list:
    """商品名・説明文から、型番っぽい文字列を複数拾う（本当の型番かは分からないので、候補として全部出す）。
    例：「PR 17ZS」「0PR 17ZS」「1BA252」「GG0061S」。"""
    text = " ".join(t for t in texts if t)
    # URL・メールアドレス・「〜.com/〜」のような文字列は型番ではないので先に取り除く
    text = re.sub(r"https?://\S+|\b[\w.\-]+\.(?:com|jp|net|org|html?)\S*|\S+@\S+", " ", text)
    cands = []

    def add(tok):
        tok = tok.strip(" -_./")
        if len(tok) < 4 or _MODEL_STOP_RE.match(tok):
            return
        if not any(c.isdigit() for c in tok) or "/" in tok:
            return
        if tok not in cands and not any(tok in c for c in cands):
            cands.append(tok)

    # 「0PR 17ZS」のように、スペースで区切られた型番
    for m in re.finditer(r"\b([0-9]?[A-Z]{1,4}\s\d{2,4}[A-Z0-9]{0,4})\b", text):
        add(m.group(1))
    for m in re.finditer(r"[A-Za-z0-9][A-Za-z0-9\-_./]{3,}", text):
        add(m.group(0))
    return cands[:limit]


# ---- 日本語→英語（検索ワード用）。まず辞書で変換し、残った日本語だけ無料の翻訳(MyMemory)に任せる ----
_JA_EN_GLOSSARY = [
    ("メンズ", "men's"), ("レディース", "women's"), ("ユニセックス", "unisex"), ("キッズ", "kids"),
    ("スウェットパンツ", "sweatpants"), ("スウェット", "sweatshirt"), ("パーカー", "hoodie"), ("フーディー", "hoodie"),
    ("フーディ", "hoodie"), ("トレーナー", "sweatshirt"), ("Tシャツ", "t-shirt"), ("ポロシャツ", "polo shirt"),
    ("シャツ", "shirt"), ("ブラウス", "blouse"), ("ニット", "knit"), ("セーター", "sweater"), ("カーディガン", "cardigan"),
    ("ジャケット", "jacket"), ("ブルゾン", "bomber jacket"), ("ジャンバー", "jacket"), ("コート", "coat"), ("ダウン", "down jacket"),
    ("トラックパンツ", "track pants"), ("パンツ", "pants"), ("デニム", "denim"), ("ジーンズ", "jeans"), ("ショートパンツ", "shorts"),
    ("ハーフパンツ", "shorts"), ("スカート", "skirt"), ("ワンピース", "dress"), ("レギンス", "leggings"), ("タンクトップ", "tank top"),
    ("トートバッグ", "tote bag"), ("ショルダーバッグ", "shoulder bag"), ("ハンドバッグ", "handbag"), ("リュック", "backpack"),
    ("バックパック", "backpack"), ("バッグ", "bag"), ("ポーチ", "pouch"), ("財布", "wallet"), ("長財布", "long wallet"),
    ("キーケース", "key case"), ("カードケース", "card case"), ("ベルト", "belt"), ("サングラス", "sunglasses"), ("メガネ", "glasses"),
    ("ネックレス", "necklace"), ("ブレスレット", "bracelet"), ("ピアス", "earrings"), ("イヤリング", "earrings"), ("リング", "ring"),
    ("指輪", "ring"), ("時計", "watch"), ("腕時計", "watch"), ("スニーカー", "sneakers"), ("ブーツ", "boots"), ("サンダル", "sandals"),
    ("ローファー", "loafers"), ("パンプス", "pumps"), ("シューズ", "shoes"), ("靴下", "socks"), ("ソックス", "socks"),
    ("マフラー", "scarf"), ("ストール", "stole"), ("スカーフ", "scarf"), ("手袋", "gloves"), ("グローブ", "gloves"),
    ("キャップ", "cap"), ("帽子", "hat"), ("ハット", "hat"), ("ビーニー", "beanie"), ("ヘアゴム", "scrunchie"),
    ("ブラック", "black"), ("ホワイト", "white"), ("ネイビー", "navy"), ("グレー", "gray"), ("ベージュ", "beige"),
    ("ブラウン", "brown"), ("グリーン", "green"), ("ブルー", "blue"), ("レッド", "red"), ("ピンク", "pink"), ("黒", "black"), ("白", "white"),
    ("ロゴ", "logo"), ("刺繍", "embroidered"), ("ダメージ加工", "distressed"), ("オーバーサイズ", "oversized"),
    ("セットアップ", "set"), ("ジップ", "zip"), ("半袖", "short sleeve"), ("長袖", "long sleeve"), ("レザー", "leather"),
    ("本革", "leather"), ("ウール", "wool"), ("カシミヤ", "cashmere"), ("デザイン", "design"),
]
_JA_EN_GLOSSARY.sort(key=lambda kv: -len(kv[0]))
_JA_RUN_RE = re.compile(r"[぀-ヿ一-鿿＀-￯ー・]+")


@st.cache_data(ttl=86400, show_spinner=False)
def _translate_free(text: str) -> str:
    """辞書で訳せなかった日本語だけを、無料の翻訳サービス（MyMemory・キー不要）で英語にする。失敗したら空文字。"""
    try:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text, "langpair": "ja|en"}, timeout=12,
        )
        d = r.json()
        if d.get("responseStatus") == 200 and not d.get("quotaFinished"):
            out = (d.get("responseData") or {}).get("translatedText") or ""
            return "" if _JA_RUN_RE.search(out) else out.strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def to_english(text: str) -> str:
    """商品名などの日本語を英語に直す。英字（ブランド名・型番）はそのまま残す。"""
    t = clean_name(text or "")
    for ja, en in _JA_EN_GLOSSARY:
        t = t.replace(ja, f" {en} ")
    for run in set(_JA_RUN_RE.findall(t)):
        if len(run) >= 2:
            t = t.replace(run, f" {_translate_free(run)} ")
        else:
            t = t.replace(run, " ")
    t = _JA_RUN_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    seen, words = set(), []
    for w in t.split(" "):  # 同じ単語の重複を除く（例：sweatpants sweatpants）
        if w.lower() not in seen:
            seen.add(w.lower())
            words.append(w)
    return " ".join(words)


_MODEL_LABEL_RE = re.compile(
    r"(?:品番|型番|商品番号|商品コード|モデル番号|モデルナンバー|スタイルナンバー|"
    r"Model(?:\s*(?:No\.?|Number|code))?|Style(?:\s*(?:No\.?|Number|code))?|Ref(?:erence)?\.?|SKU|"
    r"Item\s*(?:No\.?|Number)|Article(?:\s*(?:No\.?|Number))?|Product\s*code)"
    r"\s*[:：#＃\-\s]\s*([A-Za-z0-9][A-Za-z0-9\-_./ ]{2,24}?)(?=\s*(?:[\n\r、。,;/）)】]|\s{2,}|$|[ぁ-んァ-ヶ一-龥]))",
    re.I,
)


def extract_labeled_models(*texts: str) -> list:
    """商品ページに「品番：」「型番：」「Model:」「Style No.」などと**書かれているものだけ**を拾う。"""
    text = "\n".join(t for t in texts if t)
    out = []
    for m in _MODEL_LABEL_RE.finditer(text):
        v = m.group(1).strip(" -_./")
        if len(v) >= 3 and any(c.isdigit() for c in v) and v not in out:
            out.append(v)
    return out[:6]


_PASTE_SKIP_DOMAINS = (
    "google.", "gstatic.", "youtube.", "instagram.", "facebook.", "pinterest.", "twitter.", "x.com",
    "tiktok.", "buyma.com", "wikipedia.", "line.me", "t.co",
)


def extract_urls_from_text(text: str) -> list:
    """貼り付けられた文章から、商品ページっぽいURLを取り出す。
    ふつうのURLに加えて、Googleの検索結果に表示される「サイト名 › products › 商品名」の形も、URLに直して拾う。"""
    urls = []
    for m in re.finditer(r"https?://[^\s<>\"'）)」】]+", text or ""):
        rest = (text or "")[m.end():m.end() + 6]
        if "›" in rest:  # 「サイト名 › products › 商品名」形式の先頭部分なので、下で組み立て直す
            continue
        urls.append(m.group(0).rstrip(".,;、。"))
    for m in re.finditer(r"(?:https?://)?((?:[a-z0-9][a-z0-9\-]*\.)+[a-z]{2,})((?:\s*›\s*[^\s›]+)+)", text or "", re.I):
        parts = [x.strip() for x in re.split(r"\s*›\s*", m.group(2)) if x.strip()]
        if not parts or any(("…" in x or "..." in x) for x in parts):
            continue
        urls.append("https://" + m.group(1) + "/" + "/".join(parts))
    out = []
    for u in urls:
        pu = urlparse(u)
        host = pu.netloc.lower()
        if not host or any(d in host for d in _PASTE_SKIP_DOMAINS) or pu.path in ("", "/"):
            continue  # トップページ（商品ページではない）は除く
        u = u.split("#")[0]
        if u not in out:
            out.append(u)
    return out


def google_search_url(domain: str, hl: str, gl: str, query: str, shopping: bool = False) -> str:
    q = quote_plus(query)
    base = f"https://www.{domain}/search?q={q}&hl={hl}&gl={gl}&pws=0"
    return base + ("&tbm=shop" if shopping else "")


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_buyma_item_info(url: str) -> dict:
    """BUYMAの売れた商品ページから、タイトル・ブランド・売価・画像・説明文を読み取る。"""
    html = fetch(url)
    info = parse_buyma_product(html)
    desc = ""
    for node in _iter_jsonld(html):
        if isinstance(node, dict) and node.get("@type") in ("Product", "ProductGroup") and node.get("description"):
            desc = str(node["description"])
            break
    # BUYMA正式の商品名は「ブランド名＋カテゴリ」程度のことが多く、出品者が付けた英語の商品名・型番は
    # パンくずリストの最後の項目に入っているので、そちらを「出品者タイトル」として使う。
    seller_title = ""
    for node in _iter_jsonld(html):
        if isinstance(node, dict) and node.get("@type") == "BreadcrumbList":
            names = [(i.get("name") or (i.get("item") or {}).get("name") or "") for i in node.get("itemListElement", [])]
            if names and names[-1]:
                seller_title = names[-1]
    images = []
    for node in _iter_jsonld(html):
        if isinstance(node, dict) and node.get("@type") in ("Product", "ProductGroup"):
            variants = node.get("hasVariant") if node.get("@type") == "ProductGroup" else [node]
            for v in (variants or [])[:1]:
                imgs = v.get("image") if isinstance(v, dict) else None
                for u in (imgs if isinstance(imgs, list) else [imgs] if imgs else []):
                    if isinstance(u, str) and u not in images:
                        images.append(u)
    info["images"] = images[:12] or ([info["image"]] if info.get("image") else [])
    info["title"] = seller_title or info.get("name") or ""
    info["description"] = desc
    info["url"] = url
    info["labeled_models"] = extract_labeled_models(info["title"], desc)
    info["model_candidates"] = guess_model_candidates(info["title"], info.get("name") or "", desc)
    info["title_en"] = to_english(info["title"])
    # BUYMAのカテゴリー（パンくずの中ほど）も英語にして、検索ワードに使う
    cats = []
    for node in _iter_jsonld(html):
        if isinstance(node, dict) and node.get("@type") == "BreadcrumbList":
            names = [(i.get("name") or (i.get("item") or {}).get("name") or "") for i in node.get("itemListElement", [])]
            if any(n.startswith(("メンズ", "レディース")) for n in names):
                cats = [n for n in names[1:-1] if n]
    info["category_en"] = to_english(" ".join(cats[-1:])) or category_en(info["title"])
    return info


def _abs_url(base: str, href: str) -> str:
    return urljoin(base, href) if href else ""


def _extract_contacts(html: str, base_url: str) -> dict:
    soup = soupify(html)
    phones, emails, pages = [], [], []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        text = a.get_text(" ", strip=True).lower()
        if low.startswith("tel:"):
            ph = re.sub(r"[^\d+]", "", href[4:])
            if len(ph) >= 7 and ph not in phones:
                phones.append(ph)
        elif low.startswith("mailto:"):
            em = href[7:].split("?")[0].strip()
            if em and em not in emails:
                emails.append(em)
        elif any(w in low or w in text for w in _CONTACT_WORDS):
            if low.startswith(("#", "javascript:")):
                continue
            u = _abs_url(base_url, href)
            same = u.split("#")[0].rstrip("/") == base_url.split("#")[0].rstrip("/")
            if u.startswith("http") and not same and u not in pages:
                pages.append(u)
    body = soup.get_text(" ", strip=True)
    for m in re.finditer(r"(?:Tel|TEL|Phone|Call|電話|Telefon|Téléphone)[^\d+]{0,10}(\+?\d[\d\s().\-]{7,}\d)", body):
        ph = re.sub(r"[^\d+]", "", m.group(1))
        if len(ph) >= 7 and ph not in phones:
            phones.append(ph)
    for m in re.finditer(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", body):
        em = m.group(0)
        if em not in emails and not em.lower().endswith((".png", ".jpg", ".webp")):
            emails.append(em)
    return {"phones": phones[:3], "emails": emails[:3], "pages": pages[:3]}


def _stock_from_shopify(url: str):
    """ShopifyのサイトならURLの末尾に .js を付けると、サイズ別の在庫（在庫あり／なし）が取れる。"""
    p = urlparse(url)
    m = re.match(r"(.*?/products/[^/?#]+)", p.path)
    if not m:
        return None
    try:
        data = json.loads(fetch(f"{p.scheme}://{p.netloc}{m.group(1)}.js"))
    except Exception:  # noqa: BLE001
        return None
    variants = data.get("variants") or []
    if not variants:
        return None
    return [(str(v.get("title") or v.get("option1") or "?"), bool(v.get("available"))) for v in variants]


def _stock_from_jsonld(html: str):
    out = []
    for node in _iter_jsonld(html):
        if not isinstance(node, dict):
            continue
        variants = node.get("hasVariant") if node.get("@type") == "ProductGroup" else None
        for v in variants or []:
            if not isinstance(v, dict):
                continue
            label = v.get("size") or v.get("name") or v.get("sku") or "?"
            offers = _find_offers(v)
            if offers:
                avail = str(offers[0].get("availability") or "")
                out.append((str(label), avail.endswith(("InStock", "LimitedAvailability", "PreOrder"))))
    return out or None


# ---- VAT（付加価値税）：表示価格に税が含まれているか／含まれていない場合の想定額 ----
_VAT_STATUSES = ["税込み", "税込み（推定）", "税抜き", "不明"]
# 国ごとの標準的なVAT率の目安（ドメインの末尾から判断。商品によって軽減税率などで違うことがある）
_VAT_RATE_BY_TLD = {
    "it": 22, "fr": 20, "de": 19, "es": 21, "uk": 20, "nl": 21, "be": 21, "at": 20, "ie": 23, "pt": 23,
    "se": 25, "dk": 25, "fi": 25.5, "pl": 23, "gr": 24, "ch": 8.1, "kr": 10, "au": 10, "cz": 21, "hu": 27,
    "no": 25, "lu": 17, "mt": 18, "ee": 22, "lv": 21, "lt": 21, "sk": 23, "si": 22, "hr": 25, "bg": 20, "ro": 19,
}
_VAT_INCLUDED_RE = re.compile(
    r"(iva\s*(?:inclusa|compresa|incl)|tasse\s*incluse|tax(?:es)?\s*included|incl\.?\s*(?:vat|tax)|inc\.?\s*vat|"
    r"vat\s*included|inkl\.?\s*(?:mwst|ust)|tva\s*(?:incluse|comprise)|\bttc\b|iva\s*incluido|impuestos\s*incluidos|"
    r"부가세\s*포함|세금\s*포함|税込|消費税込)", re.I)
_VAT_EXCLUDED_RE = re.compile(
    r"(excl\.?\s*(?:vat|tax)|vat\s*(?:excluded|not included)|tax(?:es)?\s*(?:excluded|not included)|"
    r"zzgl\.?\s*(?:mwst|ust)|iva\s*esclusa|hors\s*taxes|plus\s*(?:sales\s*)?tax|"
    r"taxes?\s*(?:and\s*shipping\s*)?calculated\s*at\s*checkout|税抜|税別)", re.I)


def _vat_rate_for(url: str, currency: str):
    host = urlparse(url).netloc.lower()
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    if host.endswith(".co.uk"):
        tld = "uk"
    if tld in _VAT_RATE_BY_TLD:
        return _VAT_RATE_BY_TLD[tld]
    if currency == "GBP":
        return 20
    return None  # .com・EURでも国が分からない場合などは、手入力してもらう


def detect_vat(html: str, url: str, currency: str) -> dict:
    """価格に税（VAT）が含まれているかを、ページの記載・構造化データ・国の傾向から判定する。"""
    rate = _vat_rate_for(url, currency)
    for node in _iter_jsonld(html):
        flag = _find_key(node, "valueAddedTaxIncluded")
        if flag is not None:
            inc = str(flag).lower() in ("true", "1")
            return {"VAT表示": "税込み" if inc else "税抜き", "VAT率": rate, "VAT根拠": "ページの構造化データに明記"}
    body = soupify(html).get_text(" ", strip=True)
    m = _VAT_INCLUDED_RE.search(body)
    if m:
        return {"VAT表示": "税込み", "VAT率": rate, "VAT根拠": f"ページに「{m.group(0)}」と記載"}
    m = _VAT_EXCLUDED_RE.search(body)
    if m:
        return {"VAT表示": "税抜き", "VAT率": rate, "VAT根拠": f"ページに「{m.group(0)}」と記載"}
    if rate:
        return {"VAT表示": "税込み（推定）", "VAT率": rate, "VAT根拠": "記載なし。国の傾向（個人向けの価格は税込みが一般的）"}
    return {"VAT表示": "不明", "VAT率": None, "VAT根拠": "記載なし。国も特定できませんでした"}


def _find_key(node, key):
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            r = _find_key(v, key)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_key(v, key)
            if r is not None:
                return r
    return None


def _signed_yen(v: int) -> str:
    return f"−¥{abs(v):,}" if v < 0 else f"¥{v:,}"


def vat_free_yen(yen_value, status: str, rate):
    """VATが含まれている（またはその可能性がある）価格から、VATを除いた想定の円額を返す。税抜きなら、そのまま。"""
    try:
        y = float(yen_value)
    except (TypeError, ValueError):
        return None
    if y != y:  # 読み取れなかった行（空欄）はNaNになるので、計算しない
        return None
    try:
        r = float(rate)
    except (TypeError, ValueError):
        r = 0.0
    if status == "税抜き" or r <= 0:
        return int(round(y))
    return int(round(y / (1 + r / 100)))


_BLOCK_MARKERS = (
    "isBotPage", "Access Denied", "Just a moment", "cf-browser-verification", "captcha", "Attention Required",
    "errors.edgesuite.net", "Pardon Our Interruption", "unusual traffic", "px-captcha",
)


def _looks_blocked(html: str) -> bool:
    """ロボット（自動アクセス）を防ぐためのページが返ってきたかを判定する。"""
    h = html or ""
    has_product_data = "application/ld+json" in h and ('"Product"' in h or '"ProductGroup"' in h)
    return (not has_product_data) and any(m.lower() in h.lower() for m in _BLOCK_MARKERS)


# ---- 楽天市場・Yahoo!ショッピング（ツールから読める。ショップの会社概要ページも自動で取る）----
def _clean_jp_title(title: str):
    """「【楽天市場】商品名：ショップ名」「商品名 : ストア名 - 通販 - Yahoo!ショッピング」から、商品名とショップ名を分ける。"""
    t = (title or "").strip()
    shop = ""
    m = re.match(r"^(.*?)\s*[:：]\s*([^:：]+?)\s*-\s*通販\s*-\s*Yahoo!ショッピング$", t)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    if t.startswith("【楽天市場】"):
        t = t[len("【楽天市場】"):]
        if "：" in t:
            t, shop = t.rsplit("：", 1)
    return t.strip(), shop.strip()


def _jp_shop_lines(page_html: str) -> list:
    """会社概要ページの文章から、ショップ情報の行（会社名・責任者・住所・電話・営業時間など）を作る。"""
    raw_lines = soupify(page_html).get_text("\n", strip=True).split("\n")
    kept, skip_next = [], False
    for ln in raw_lines:  # FAX番号は連絡先に入れない（FAXの行と、その次の番号だけの行を除く）
        if skip_next:
            skip_next = False
            if not re.search(r"[A-Za-z\u3040-\u30ff\u4e00-\u9fff]", ln):
                continue
        if re.search(r"FAX|Fax|ファックス|ファクス", ln):
            skip_next = not re.search(r"\d{2,4}-\d{2,4}-\d{3,4}", ln)
            continue
        kept.append(ln)
    text = "\n".join(kept)
    got = parse_shop_info(text)
    out = []
    company = next((ln for ln in text.split("\n") if re.match(r"^(株式会社|有限会社|合同会社)\S{1,30}$", ln.strip())), "")
    if company:
        out.append(f"会社名：{company.strip()}")
    for lab in ("ストア名", "販売業者", "運営会社", "運営責任者", "店舗運営責任者", "代表者"):
        if lab in got["fields"]:
            out.append(f"{lab}：{got['fields'][lab]}")
    addr = next((ln.strip() for ln in text.split("\n") if ln.strip().startswith("〒") and len(ln.strip()) > 10), "")
    if addr:
        out.append(f"所在地：{addr}")
    elif "住所" in got["fields"]:
        out.append(f"所在地：{got['fields']['住所']}")
    return out, got


def enrich_marketplace(row: dict, html: str, url: str, light: bool) -> dict:
    """楽天市場・Yahoo!ショッピングの商品ページなら、商品名・価格・在庫・ショップ情報を追加で読み取る。"""
    p = urlparse(url)
    host, parts = p.netloc.lower(), [x for x in p.path.split("/") if x]
    shop_id, info_url, market = "", "", ""
    if host == "item.rakuten.co.jp" and parts:
        market, shop_id = "楽天市場", parts[0]
        info_url = f"https://www.rakuten.co.jp/{shop_id}/info.html"
    elif host == "store.shopping.yahoo.co.jp" and parts:
        market, shop_id = "Yahoo!ショッピング", parts[0]
        info_url = f"https://store.shopping.yahoo.co.jp/{shop_id}/info.html"
    elif host == "paypaymall.yahoo.co.jp" and len(parts) >= 2 and parts[0] == "store":
        market, shop_id = "Yahoo!ショッピング", parts[1]
        info_url = f"https://store.shopping.yahoo.co.jp/{shop_id}/info.html"
    if not market:
        return row
    row = dict(row)
    title, shop_name = _clean_jp_title(row.get("仕入れ先商品名") or "")
    if title:
        row["仕入れ先商品名"] = title
    # 価格（楽天はページ内のデータに入っている）
    if not row.get("円換算"):
        m = re.search(r'"minPrice":([\d.]+)', html) or re.search(r'"taxIncludedPrice":([\d.]+)', html)
        if m:
            row["現地価格"], row["通貨"], row["円換算"] = float(m.group(1)), "JPY", int(float(m.group(1)))
    if row.get("通貨") == "JPY":
        row["VAT表示"], row["VAT率"], row["VAT根拠"] = "税込み", 10, "日本のショップ（日本の価格表示は消費税込み）"
    # 楽天：サイズ別の在庫
    if market == "楽天市場":
        if not shop_name:
            m = re.search(r'"shopName":\s*"([^"]+)"', html)
            shop_name = m.group(1) if m else ""
        inv = re.search(r'"variantMappedInventories":(\[.*?\])', html)
        if inv:
            qty = {x["sku"]: x["quantity"] for x in json.loads(inv.group(1))}
            labels = {}
            for m in re.finditer(r'"variantId":"([^"]+)","selectorValues":(\[[^\]]*\])', html):
                labels[m.group(1)] = " ".join(re.sub(r"（\d+）", "", v) for v in json.loads(m.group(2)))
            if len(qty) == 1:
                q = next(iter(qty.values()))
                row["在庫（サイズ別）"] = f"この商品 {'✅' if q > 0 else '❌'}（{'残り%d点' % q if q > 0 else '売り切れ'}）"
            else:
                items, unknown_out, unknown_in = [], 0, 0
                for sku, q in qty.items():
                    if sku in labels:
                        items.append(f"{labels[sku]} {'✅' if q > 0 else '❌'}" + (f"（残り{q}点）" if 0 < q < 10 else ""))
                    elif q > 0:
                        unknown_in += 1
                    else:
                        unknown_out += 1
                if unknown_in:
                    items.append(f"（サイズ不明の在庫あり {unknown_in}種）✅")
                if unknown_out:
                    items.append(f"その他 {unknown_out}種 ❌（売り切れ）")
                row["在庫（サイズ別）"] = "、".join(items)
    row["仕入れ先サイト"] = f"{market}｜{shop_name or shop_id}"
    info = [f"モール：{market}", f"ショップ：{shop_name or shop_id}"]
    if not light:
        try:
            lines, got = _jp_shop_lines(fetch(info_url))
            info += lines
            row["電話"] = row.get("電話") or " / ".join(got["phones"])
            row["メール"] = row.get("メール") or " / ".join(got["emails"])
        except Exception:  # noqa: BLE001
            info.append("（ショップの会社概要ページは読み取れませんでした）")
    row["ショップ情報"] = "\n".join(info)
    return row


def analyze_supplier(url: str, html: str = "", light: bool = False) -> dict:
    """仕入れ先の商品ページから、価格・円換算・サイズ別在庫・連絡先を読み取る。"""
    html = html or fetch(url)
    if _looks_blocked(html):
        raise PermissionError("blocked")
    soup = soupify(html)
    title = ""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    amount, currency = (extract_price_generic(html) or (None, None))
    price_note = ""
    _offers = [o for n in _iter_jsonld(html) for o in _find_offers(n)]
    _vals = []
    for o in _offers:
        try:
            _vals.append((float(str(o["price"]).replace(",", "")), "InStock" in str(o.get("availability", ""))))
        except (ValueError, TypeError, KeyError):
            pass
    if len({v for v, _ in _vals}) > 1 and currency:
        _in = [v for v, ok in _vals if ok]
        amount = min(_in) if _in else min(v for v, _ in _vals)  # 在庫のあるバリエーションの最安値を使う
        price_note = f"【バリエーションで価格が違います：{min(v for v, _ in _vals):,.2f}〜{max(v for v, _ in _vals):,.2f} {currency}。在庫ありの最安値を使っています】"
    yen_value = None
    if amount and currency:
        fx = fetch_fx_rate(currency) if currency != "JPY" else (1.0, None)
        if fx:
            yen_value = int(round(amount * fx[0]))

    stock = _stock_from_shopify(url) or _stock_from_jsonld(html)
    if stock:
        stock_text = "、".join(f"{label} {'✅' if ok else '❌'}" for label, ok in stock)
    else:
        stock_text = "サイズ別の在庫は取得できず（サイトで確認）"
    if price_note:
        stock_text = price_note + "、" + stock_text

    contacts = _extract_contacts(html, url)
    if not light and not contacts["phones"] and not contacts["emails"]:
        for page in contacts["pages"][:2]:
            try:
                more = _extract_contacts(fetch(page), page)
            except Exception:  # noqa: BLE001
                continue
            contacts["phones"] = contacts["phones"] or more["phones"]
            contacts["emails"] = contacts["emails"] or more["emails"]
            if contacts["phones"] or contacts["emails"]:
                break

    vat = detect_vat(html, url, currency or "")
    base = {
        "仕入れ先サイト": urlparse(url).netloc.replace("www.", ""),
        "仕入れ先商品名": title,
        "現地価格": amount if amount else "",
        "通貨": currency or "",
        "円換算": yen_value if yen_value else "",
        "VAT表示": vat["VAT表示"],
        "VAT率": vat["VAT率"] if vat["VAT率"] is not None else "",
        "VAT根拠": vat["VAT根拠"],
        "在庫（サイズ別）": stock_text,
        "電話": " / ".join(contacts["phones"]),
        "メール": " / ".join(contacts["emails"]),
        "問い合わせページ": contacts["pages"][0] if contacts["pages"] else "",
        "仕入れ先URL": url,
    }
    return enrich_marketplace(base, html, url, light)


# 交渉メールの例文（「{...}」の部分は自動で埋まる）。送る前に必ず内容を確認すること。
_NEGOTIATION_TEMPLATES = {
    "English": (
        "Subject: Wholesale inquiry - {product}\n\nHello,\n\n"
        "I am a professional buyer based in Japan and I am interested in purchasing the following item from your store.\n\n"
        "Item: {product}\nURL: {url}\nSize / quantity: {qty}\n\n"
        "Could you please let me know:\n"
        "1. Do you have the above sizes in stock?\n"
        "2. Do you offer a wholesale or discounted price for this quantity (and for repeat orders)?\n"
        "3. Do you ship to Japan? If so, what are the shipping cost and delivery time?\n"
        "4. Can you issue a tax-free (VAT-exempt) invoice for this export order?\n"
        "5. Which payment methods do you accept?\n\n"
        "Thank you very much. I look forward to your reply.\n\nBest regards,\n{sender}"
    ),
    "Italiano": (
        "Oggetto: Richiesta di acquisto all'ingrosso - {product}\n\nBuongiorno,\n\n"
        "sono un buyer professionista con sede in Giappone e sono interessato ad acquistare il seguente articolo dal vostro negozio.\n\n"
        "Articolo: {product}\nURL: {url}\nTaglia / quantità: {qty}\n\n"
        "Potreste gentilmente indicarmi:\n"
        "1. Le taglie indicate sono disponibili?\n"
        "2. Offrite un prezzo all'ingrosso o scontato per questa quantità (e per ordini ripetuti)?\n"
        "3. Spedite in Giappone? In caso affermativo, quali sono i costi e i tempi di spedizione?\n"
        "4. Potete emettere una fattura senza IVA per questo ordine destinato all'esportazione?\n"
        "5. Quali metodi di pagamento accettate?\n\n"
        "Grazie mille. Resto in attesa di una vostra risposta.\n\nCordiali saluti,\n{sender}"
    ),
    "Français": (
        "Objet : Demande d'achat en gros - {product}\n\nBonjour,\n\n"
        "Je suis un acheteur professionnel basé au Japon et je souhaiterais acheter l'article suivant dans votre boutique.\n\n"
        "Article : {product}\nURL : {url}\nTaille / quantité : {qty}\n\n"
        "Pourriez-vous m'indiquer :\n"
        "1. Les tailles ci-dessus sont-elles disponibles en stock ?\n"
        "2. Proposez-vous un tarif de gros ou une remise pour cette quantité (et pour des commandes régulières) ?\n"
        "3. Expédiez-vous au Japon ? Si oui, quels sont les frais et les délais de livraison ?\n"
        "4. Pouvez-vous établir une facture hors taxes (exonérée de TVA) pour cette commande à l'export ?\n"
        "5. Quels modes de paiement acceptez-vous ?\n\n"
        "Je vous remercie par avance et reste dans l'attente de votre réponse.\n\nCordialement,\n{sender}"
    ),
    "Deutsch": (
        "Betreff: Anfrage zum Großhandelskauf - {product}\n\nGuten Tag,\n\n"
        "ich bin ein professioneller Einkäufer mit Sitz in Japan und möchte den folgenden Artikel in Ihrem Shop kaufen.\n\n"
        "Artikel: {product}\nURL: {url}\nGröße / Menge: {qty}\n\n"
        "Könnten Sie mir bitte mitteilen:\n"
        "1. Sind die oben genannten Größen auf Lager?\n"
        "2. Bieten Sie für diese Menge (und für Folgebestellungen) einen Großhandels- oder Mengenrabatt an?\n"
        "3. Versenden Sie nach Japan? Wenn ja, wie hoch sind die Versandkosten und die Lieferzeit?\n"
        "4. Können Sie für diese Exportbestellung eine steuerfreie (mehrwertsteuerfreie) Rechnung ausstellen?\n"
        "5. Welche Zahlungsarten akzeptieren Sie?\n\n"
        "Vielen Dank. Ich freue mich auf Ihre Antwort.\n\nMit freundlichen Grüßen\n{sender}"
    ),
    "한국어": (
        "제목: 도매 구매 문의 - {product}\n\n안녕하세요.\n\n"
        "저는 일본에 거주하는 전문 바이어이며, 귀사의 아래 상품을 구매하고 싶어 연락드립니다.\n\n"
        "상품명: {product}\nURL: {url}\n사이즈 / 수량: {qty}\n\n"
        "아래 사항을 알려주시면 감사하겠습니다.\n"
        "1. 위 사이즈의 재고가 있나요?\n"
        "2. 해당 수량(및 재주문)에 대한 도매가 또는 할인가가 가능한가요?\n"
        "3. 일본으로 배송이 가능한가요? 가능하다면 배송비와 배송 기간을 알려주세요.\n"
        "4. 수출 주문에 대해 부가세 면세(영세율) 처리가 가능한가요?\n"
        "5. 결제 방법은 어떤 것이 가능한가요?\n\n"
        "감사합니다. 회신 기다리겠습니다.\n\n{sender} 드림"
    ),
}
_NEGOTIATION_JA = (
    "【日本語訳（確認用）】\n件名：卸売り・まとめ買いのお問い合わせ\n\n"
    "日本在住のプロのバイヤーです。貴店の下記の商品を購入したいと考えています。\n\n"
    "商品／URL／サイズ・数量は上記のとおりです。\n\n"
    "次の点を教えてください。\n"
    "1. 上記のサイズの在庫はありますか？\n"
    "2. この数量（および継続注文）に対する卸売り価格・割引はありますか？\n"
    "3. 日本へ発送できますか？送料と配送日数を教えてください。\n"
    "4. この輸出注文に対して、免税（VATなし）のインボイスを発行できますか？\n"
    "5. 利用できる支払い方法は何ですか？\n\n"
    "よろしくお願いします。"
)


def _run_parallel(func, items, workers: int = 6) -> list:
    """複数のURLを同時に読み取る（Streamlitのキャッシュを使えるよう、実行コンテキストを引き継ぐ）。"""
    ctx = get_script_run_ctx()

    def init():
        if ctx is not None:
            add_script_run_ctx(threading.current_thread(), ctx)

    with ThreadPoolExecutor(max_workers=workers, initializer=init) as ex:
        return list(ex.map(func, items))


def analyze_supplier_safe(url: str, light: bool = True) -> dict:
    try:
        return analyze_supplier(url, light=light)
    except Exception as e:  # noqa: BLE001
        status = getattr(getattr(e, "response", None), "status_code", None)
        if isinstance(e, PermissionError) or status in (401, 403, 429, 503):
            note = "🚫 このサイトは自動アクセスを防いでいるため読み取れません（ブラウザで開いて価格を確認してください）"
        else:
            note = f"読み取りエラー：{str(e)[:50]}"
        return {
            "仕入れ先サイト": urlparse(url).netloc.replace("www.", ""), "仕入れ先商品名": "（自動では読み取れませんでした）",
            "現地価格": "", "通貨": "", "円換算": "", "VAT表示": "不明", "VAT率": "", "VAT根拠": "", "在庫（サイズ別）": note,
            "電話": "", "メール": "", "問い合わせページ": "", "仕入れ先URL": url,
        }


def search_shopify_store(shop_url: str, query: str, limit: int = 5):
    """Shopify製のショップなら、サイト内検索の結果（商品ページURL）を取得する。対応していないショップはNone。"""
    p = urlparse(shop_url if shop_url.startswith("http") else "https://" + shop_url)
    if not p.netloc:
        return None
    root = f"{p.scheme}://{p.netloc}"
    try:
        r = requests.get(
            root + "/search/suggest.json",
            params={"q": query, "resources[type]": "product", "resources[limit]": limit},
            headers=HEADERS, timeout=12,
        )
        prods = r.json()["resources"]["results"]["products"]
    except Exception:  # noqa: BLE001
        return None
    return [root + pr["url"].split("?")[0] for pr in prods if pr.get("url")]


def _sourcing_rows() -> list:
    return st.session_state.setdefault("sourcing_list", [])


def _add_sourcing_row(row: dict, item: dict) -> int:
    """仕入れ先リストに1行追加（同じ仕入れ先URLがあれば、交渉済み・メモを引き継いで上書き）。件数を返す。"""
    now = dt.datetime.now()
    row = dict(row)
    row.update({
        "交渉済み": False,
        "追加日時": f"{now.year}/{now.month}/{now.day}",
        "BUYMA商品名": (item or {}).get("name") or "",
        "BUYMA売価": (item or {}).get("price") or "",
        "BUYMA商品URL": (item or {}).get("url") or "",
        "メモ": "",
    })
    row["種類"] = row.get("種類") or _site_kind(row.get("仕入れ先URL") or "")
    rows = _sourcing_rows()
    for i, existing in enumerate(rows):
        if existing.get("仕入れ先URL") == row["仕入れ先URL"]:
            row["交渉済み"], row["メモ"] = existing.get("交渉済み", False), existing.get("メモ", "")
            rows[i] = row
            return len(rows)
    rows.append(row)
    return len(rows)


def _set_sourcing_field(idx: int, field: str, widget_key: str):
    """詳細パネルで直した値（VAT表示・VAT率）を、仕入れ先リストの該当行に書き戻す。"""
    rows = st.session_state.get("sourcing_list") or []
    if 0 <= idx < len(rows):
        rows[idx][field] = st.session_state.get(widget_key)


def import_sourcing_csv(uploaded) -> int:
    df = pd.read_csv(uploaded, encoding="utf-8-sig").fillna("")
    count = 0
    rows = _sourcing_rows()
    for rec in df.to_dict("records"):
        if not rec.get("仕入れ先URL"):
            continue
        row = {c: rec.get(c, "") for c in SOURCING_COLUMNS}
        row["種類"] = row["種類"] or "セレクトショップ等"
        row["交渉済み"] = str(rec.get("交渉済み", "")).strip().lower() in ("true", "1", "はい", "✅", "済")
        for i, existing in enumerate(rows):
            if existing.get("仕入れ先URL") == row["仕入れ先URL"]:
                rows[i] = row
                break
        else:
            rows.append(row)
        count += 1
    return count


# ---- ページの文字を貼って価格を探す／手入力で補う（自動で読めないサイト用）----
_PRICE_SYMS = {"€": "EUR", "£": "GBP", "$": "USD", "₩": "KRW", "EUR": "EUR", "USD": "USD", "GBP": "GBP",
               "KRW": "KRW", "CHF": "CHF", "円": "JPY", "원": "KRW"}
_AMT_RE = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_SYM_RE = r"€|£|\$|₩|EUR|USD|GBP|KRW|CHF|円|원"
_PRICE_PRE = re.compile(rf"({_SYM_RE})\s?({_AMT_RE})")
_PRICE_POST = re.compile(rf"({_AMT_RE})\s?({_SYM_RE})")
_CURRENCY_CHOICES = ["EUR", "USD", "GBP", "KRW", "JPY", "AUD", "CAD", "CHF", "CNY", "HKD"]


def _parse_amount(s: str):
    """「1.480,00」「1,480.00」「480,00」「480」などの書き方をまとめて数字にする。"""
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        parts = s.split(sep)
        dec = sep if (len(parts) == 2 and len(parts[1]) != 3) else None
    else:
        dec = None
    try:
        if dec:
            i = s.rfind(dec)
            return float(f"{re.sub(r'[.,]', '', s[:i])}.{s[i + 1:]}")
        return float(re.sub(r"[.,]", "", s))
    except ValueError:
        return None


_YEN_PRE = re.compile(rf"[¥￥]\s?({_AMT_RE})")


def find_prices_in_text(text: str, limit: int = 6, yen_is_jpy: bool = False) -> list:
    """貼り付けたページの文章から、価格らしいもの（金額, 通貨）を、よく出てくる順に返す。"""
    counts, order = Counter(), {}
    if yen_is_jpy:  # 日本のショップのページ：「¥」は円
        for m in _YEN_PRE.finditer(text or ""):
            val = _parse_amount(m.group(1))
            if val and val >= 100:
                key = (round(val, 2), "JPY")
                counts[key] += 1
                order.setdefault(key, m.start())
    for rx, swap in ((_PRICE_PRE, False), (_PRICE_POST, True)):
        for m in rx.finditer(text or ""):
            sym, amt = (m.group(2), m.group(1)) if swap else (m.group(1), m.group(2))
            val = _parse_amount(amt)
            cur = _PRICE_SYMS.get(sym)
            if not val or val <= 0 or not cur:
                continue
            if cur not in ("JPY", "KRW") and val < 1:
                continue
            key = (round(val, 2), cur)
            counts[key] += 1
            order.setdefault(key, m.start())
    ranked = sorted(counts, key=lambda k: (-counts[k], order[k]))
    return ranked[:limit]


def _title_from_url(url: str) -> str:
    seg = [x for x in urlparse(url).path.split("/") if x]
    return re.sub(r"[-_]+", " ", seg[-1]).strip().title() if seg else ""


def fill_supplier_price(row: dict, amount: float, currency: str, page_text: str = "") -> dict:
    """読み取れなかった行に、手で入れた（または貼ったページから見つけた）価格を入れて、円換算とVATを計算し直す。"""
    row = dict(row)
    fx = (1.0, None) if currency == "JPY" else fetch_fx_rate(currency)
    row["現地価格"], row["通貨"] = amount, currency
    row["_manual"] = True
    row["円換算"] = int(round(amount * fx[0])) if fx else ""
    vat = detect_vat(page_text or "", row.get("仕入れ先URL") or "", currency)
    row["VAT表示"] = vat["VAT表示"]
    row["VAT率"] = vat["VAT率"] if vat["VAT率"] is not None else ""
    row["VAT根拠"] = vat["VAT根拠"]
    if str(row.get("仕入れ先商品名") or "").startswith("（自動"):
        row["仕入れ先商品名"] = _title_from_url(row.get("仕入れ先URL") or "") or "（商品名は手入力）"
    stock = str(row.get("在庫（サイズ別）") or "")
    if "✅" not in stock and "❌" not in stock:
        row["在庫（サイズ別）"] = "サイズ別の在庫は、ページで確認してメモ欄へ"
    return row


# ---- 画像検索用：加工していない写真を選ぶ ----
def _image_stats(url: str) -> dict:
    """写真に「赤い文字」などの加工が入っていないか、白い背景の商品写真かを調べる。"""
    try:
        from io import BytesIO
        from PIL import Image
        small = re.sub(r"/org\.(jpg|jpeg|png|webp)$", r"/428.\1", url)
        r = requests.get(small, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            r = requests.get(url, headers=HEADERS, timeout=10)
        im = Image.open(BytesIO(r.content)).convert("RGB")
        im.thumbnail((200, 200))
        px = list(im.getdata())
        n = max(len(px), 1)
        red = sum(1 for (a, b, c) in px if a > 200 and b < 80 and c < 80) / n
        w, h = im.size
        border = [im.getpixel((x, y)) for x in range(w) for y in (0, 1, h - 2, h - 1)]
        border += [im.getpixel((x, y)) for y in range(h) for x in (0, 1, w - 2, w - 1)]
        white = sum(1 for (a, b, c) in border if min(a, b, c) > 238) / max(len(border), 1)
        return {"url": url, "thumb": small, "red": red, "white": white}
    except Exception:  # noqa: BLE001
        return {"url": url, "thumb": url, "red": 0.0, "white": 0.0}


@st.cache_data(ttl=3600, show_spinner=False)
def score_item_images(urls: tuple) -> list:
    with ThreadPoolExecutor(max_workers=6) as ex:
        stats = list(ex.map(_image_stats, urls))
    med = statistics.median(x["red"] for x in stats) if stats else 0.0
    for x in stats:
        # 他の写真より、赤い部分が明らかに多い＝「サイズ有り」などの赤い文字が入った加工写真
        x["edited"] = x["red"] > 0.0015 and x["red"] > 3 * med + 0.001
    return stats


def pick_clean_image(stats: list) -> int:
    """加工なし＋白い背景の商品写真を優先して選ぶ。無ければ、加工なしの最初の写真。"""
    for i, x in enumerate(stats):
        if not x["edited"] and x["white"] >= 0.9:
            return i
    for i, x in enumerate(stats):
        if not x["edited"]:
            return i
    return 0


# ---- 公式サイト ----
# ブランドの公式サイトのドメイン（Googleで「site:ドメイン」検索するのに使う。国ごとのページは、各国のGoogleで検索すると出てくる）
_OFFICIAL_SITES = {
    "MAX MARA": "maxmara.com", "WEEKEND MAX MARA": "maxmara.com", "S MAX MARA": "maxmara.com",
    "LOUIS VUITTON": "louisvuitton.com", "SAINT LAURENT": "ysl.com", "BOTTEGA VENETA": "bottegaveneta.com",
    "THE NORTH FACE": "thenorthface.com", "STONE ISLAND": "stoneisland.com", "CHRISTIAN DIOR": "dior.com",
    "DIOR": "dior.com", "CHANEL": "chanel.com", "HERMES": "hermes.com", "GUCCI": "gucci.com",
    "PRADA": "prada.com", "FENDI": "fendi.com", "CELINE": "celine.com", "BALENCIAGA": "balenciaga.com",
    "BURBERRY": "burberry.com", "MIU MIU": "miumiu.com", "VALENTINO": "valentino.com", "GIVENCHY": "givenchy.com",
    "GOYARD": "goyard.com", "MONCLER": "moncler.com", "LOEWE": "loewe.com", "COACH": "coach.com",
    "TORY BURCH": "toryburch.com", "MICHAEL KORS": "michaelkors.com", "KATE SPADE": "katespade.com",
    "MARC JACOBS": "marcjacobs.com", "ALEXANDER MCQUEEN": "alexandermcqueen.com", "OFF WHITE": "off---white.com",
    "AMI PARIS": "amiparis.com", "JIL SANDER": "jilsander.com", "MACKAGE": "mackage.com", "STUSSY": "stussy.com",
    "ADIDAS": "adidas.com", "NIKE": "nike.com", "NEW BALANCE": "newbalance.com", "UGG": "ugg.com",
    "STEVE MADDEN": "stevemadden.com", "VERSACE": "versace.com", "GIORGIO ARMANI": "armani.com", "ARMANI": "armani.com",
    "SALVATORE FERRAGAMO": "ferragamo.com", "FERRAGAMO": "ferragamo.com", "TODS": "tods.com",
    "JIMMY CHOO": "jimmychoo.com", "MANOLO BLAHNIK": "manoloblahnik.com", "ROGER VIVIER": "rogervivier.com",
    "CARTIER": "cartier.com", "TIFFANY": "tiffany.com", "BVLGARI": "bulgari.com", "MONTBLANC": "montblanc.com",
    "MAISON MARGIELA": "maisonmargiela.com", "KENZO": "kenzo.com", "LANVIN": "lanvin.com",
    "THOM BROWNE": "thombrowne.com", "VETEMENTS": "vetements.com", "BALMAIN": "balmain.com", "CHLOE": "chloe.com",
    "MULBERRY": "mulberry.com", "LONGCHAMP": "longchamp.com", "FURLA": "furla.com", "PATAGONIA": "patagonia.com",
    "CANADA GOOSE": "canadagoose.com", "BARBOUR": "barbour.com", "SUPREME": "supreme.com", "VANS": "vans.com",
    "CONVERSE": "converse.com", "RALPH LAUREN": "ralphlauren.com", "ALO YOGA": "aloyoga.com",
}


def official_domain_for(brand: str) -> str:
    """ブランド名（英語）から、公式サイトのドメインを探す。見つからなければ空文字。"""
    key = re.sub(r"[^A-Z0-9 ]", "", re.sub(r"[&'’\-]", " ", (brand or "").upper()))
    key = re.sub(r"\s+", " ", key).strip()
    if key in _OFFICIAL_SITES:
        return _OFFICIAL_SITES[key]
    for name in sorted(_OFFICIAL_SITES, key=len, reverse=True):
        if name in key:
            return _OFFICIAL_SITES[name]
    return ""


def _clean_domain(text: str) -> str:
    d = (text or "").strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    return re.sub(r"^www\.", "", d)


def _site_kind(url: str, official: str = None) -> str:
    dom = _clean_domain(official if official is not None else st.session_state.get("src_official_domain", ""))
    host = urlparse(url).netloc.lower().replace("www.", "")
    if dom and (host == dom or host.endswith("." + dom)):
        return "公式サイト"
    return "セレクトショップ等"


# ---- ショップ情報（ZOZOTOWNなど、ツールから読めないページのコピーから拾う）----
_SHOP_LABELS = [
    "販売業者", "販売事業者", "運営会社", "運営事業者", "運営責任者", "事業者名", "会社名", "店舗名", "ショップ名", "屋号",
    "代表者", "責任者", "所在地", "住所", "電話番号", "TEL", "Tel", "電話", "メールアドレス", "E-mail", "Email", "営業時間",
    "ストア名", "お問い合わせ電話番号", "お問い合わせメールアドレス", "お問い合わせ", "問い合わせ先", "返品・交換", "返品", "交換", "支払い方法", "配送方法", "送料",
]
_JP_PHONE_RE = re.compile(r"(?<![\d-])(0\d{1,4}[-−ー‐－]\d{1,4}[-−ー‐－]\d{3,4})(?![\d-])")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def parse_shop_info(text: str) -> dict:
    """貼り付けたショップ情報のページから、電話・メール・会社名・所在地などを拾う。"""
    text = (text or "").replace("\r", "")
    phones = [re.sub(r"[−ー‐－]", "-", m) for m in _JP_PHONE_RE.findall(text)]
    emails = [e for e in _EMAIL_RE.findall(text) if not e.lower().endswith((".png", ".jpg", ".webp"))]
    lines = [ln.strip() for ln in text.split("\n")]
    fields = {}
    for i, ln in enumerate(lines):
        for lab in sorted(_SHOP_LABELS, key=len, reverse=True):
            if ln.startswith(lab):
                rest = re.sub(r"^[\s:：\t]+", "", ln[len(lab):])
                if not rest:  # 値が次の行にあるとき
                    nxt = next((x for x in lines[i + 1:i + 4] if x), "")
                    rest = nxt if not any(nxt.startswith(l2) for l2 in _SHOP_LABELS) else ""
                if rest and lab not in fields and len(rest) <= 200:
                    fields[lab] = rest
                break
    return {
        "phones": list(dict.fromkeys(phones))[:3],
        "emails": list(dict.fromkeys(emails))[:3],
        "fields": fields,
    }


_NOT_COLOR_WORDS = ("完売", "カート", "店舗在庫", "サイズ相当", "入荷", "お気に入り", "詳細", "しました", "在庫", "残り")
_STOCK_LINE_RE = re.compile(r"^(\S{1,12})\s*/\s*(在庫なし|在庫あり|残り\s*\d+\s*点|残りわずか|売り切れ|完売|SOLD OUT)")


def parse_pasted_extras(text: str) -> dict:
    """貼り付けたページ（ZOZOTOWNなど）から、サイズ別の在庫・商品名・ショップの情報を拾う。"""
    lines = [ln.strip() for ln in (text or "").replace("\r", "").split("\n")]
    ne = [(i, ln) for i, ln in enumerate(lines) if ln]
    stock, color, info, title = [], "", [], ""
    for k, (i, ln) in enumerate(ne):
        m = _STOCK_LINE_RE.match(ln)
        nxt = ne[k + 1][1] if k + 1 < len(ne) else ""
        if m:
            status = m.group(2)
            ok = status not in ("在庫なし", "売り切れ", "完売", "SOLD OUT")
            extra = f"（{re.sub(chr(32), '', status)}）" if ok and status != "在庫あり" else ""
            label = f"{color} {m.group(1)}".strip()
            stock.append(f"{label} {'✅' if ok else '❌'}{extra}")
        elif (_STOCK_LINE_RE.match(nxt) and len(ln) <= 12 and not any(w in ln for w in _NOT_COLOR_WORDS)):
            color = ln
        elif ln == "お気に入りアイテム登録者数" and k > 0 and not title:
            title = ne[k - 1][1]
        elif ln == "発送元" and nxt:
            info.append(f"発送元：{nxt}")
        elif ln == "問い合わせ番号":
            for _, v in ne[k + 1:k + 4]:
                if re.search(r"[（(](ZOZO|店舗)[）)]", v):
                    info.append(("ZOZOの番号：" if "ZOZO" in v else "店舗の品番：") + re.sub(r"[（(](ZOZO|店舗)[）)]", "", v))
                else:
                    break
        elif ln == "取り扱いショップ" and nxt:
            kana = ne[k + 2][1] if k + 2 < len(ne) else ""
            info.append(f"ショップ：{nxt}" + (f"（{kana}）" if kana and not kana.startswith("ショップ") else ""))
    if "店舗在庫確認・取り置き" in (text or ""):
        info.append("店舗：実店舗の在庫を確認・取り置きできる商品です")
    return {"stock": "、".join(stock), "info": info, "title": title}


def _guess_currency(url: str) -> str:
    """ショップのURLの国から、使っていそうな通貨を推測する（手入力のときの初期値）。"""
    host = urlparse(url).netloc.lower()
    tld = host.rsplit(".", 1)[-1]
    if host.endswith(".co.uk") or tld == "uk":
        return "GBP"
    return {"jp": "JPY", "kr": "KRW", "au": "AUD", "ca": "CAD", "ch": "CHF", "cn": "CNY", "hk": "HKD",
            "it": "EUR", "fr": "EUR", "de": "EUR", "es": "EUR", "nl": "EUR", "at": "EUR", "be": "EUR",
            "pt": "EUR", "ie": "EUR", "fi": "EUR", "gr": "EUR"}.get(tld, "USD")


def _is_japan_shop(row: dict) -> bool:
    host = urlparse(str(row.get("仕入れ先URL") or "")).netloc.lower()
    return str(row.get("通貨") or "") == "JPY" or host.endswith(".jp") or host.endswith("zozo.jp")


# 国ごとの標準的なVAT（付加価値税）の税率の目安（%）。商品によって軽減税率があることもある。
_VAT_COUNTRIES = {
    "🇮🇹 イタリア": 22, "🇫🇷 フランス": 20, "🇩🇪 ドイツ": 19, "🇪🇸 スペイン": 21, "🇬🇧 イギリス": 20,
    "🇳🇱 オランダ": 21, "🇧🇪 ベルギー": 21, "🇦🇹 オーストリア": 20, "🇵🇹 ポルトガル": 23, "🇮🇪 アイルランド": 23,
    "🇬🇷 ギリシャ": 24, "🇸🇪 スウェーデン": 25, "🇩🇰 デンマーク": 25, "🇫🇮 フィンランド": 25.5, "🇨🇭 スイス": 8.1,
    "🇰🇷 韓国": 10, "🇦🇺 オーストラリア": 10, "🇨🇦 カナダ（GST）": 5, "🇺🇸 アメリカ（VATなし）": 0, "🇯🇵 日本": 10,
}
_TLD_VAT_COUNTRY = {
    "it": "🇮🇹 イタリア", "fr": "🇫🇷 フランス", "de": "🇩🇪 ドイツ", "es": "🇪🇸 スペイン", "uk": "🇬🇧 イギリス",
    "nl": "🇳🇱 オランダ", "be": "🇧🇪 ベルギー", "at": "🇦🇹 オーストリア", "pt": "🇵🇹 ポルトガル", "ie": "🇮🇪 アイルランド",
    "gr": "🇬🇷 ギリシャ", "se": "🇸🇪 スウェーデン", "dk": "🇩🇰 デンマーク", "fi": "🇫🇮 フィンランド", "ch": "🇨🇭 スイス",
    "kr": "🇰🇷 韓国", "au": "🇦🇺 オーストラリア", "ca": "🇨🇦 カナダ（GST）", "jp": "🇯🇵 日本",
}


def _set_vat_country(idx: int, country_key: str, rate_key: str):
    """国を選んだら、その国の税率をVAT率の欄と、リストの該当行に入れる。"""
    name = st.session_state.get(country_key)
    rate = _VAT_COUNTRIES.get(name)
    rows = st.session_state.get("sourcing_list") or []
    if rate is not None and 0 <= idx < len(rows):
        rows[idx]["VAT率"] = rate
        st.session_state[rate_key] = float(rate)


def _has_yen(c: dict) -> bool:
    try:
        return float(c.get("円換算")) > 0
    except (TypeError, ValueError):
        return False



def _head(title: str, help_md: str = "", level: int = 2, label: str = "❓ 解説"):
    """見出しの右側に「解説」ボタンを置く。押すと説明が出る（普段は説明を出さず、画面をすっきりさせる）。"""
    c1, c2 = st.columns([5, 1])
    with c1:
        (st.header if level == 2 else st.subheader)(title)
    if help_md:
        with c2:
            st.write("")
            with st.popover(label, use_container_width=True):
                st.markdown(help_md)


def render_sourcing_tool():
    _head(
        "🛒 仕入れ先リサーチ",
        "**BUYMAで売れている商品の、海外の仕入れ先を探して、いくら安く仕入れられるかを比べるツールです。**\n\n"
        "やることは3つだけです。\n\n1. BUYMAの商品ページのURLを貼る\n2. 海外のGoogleで探す\n3. 見つけたページを貼る\n\n"
        "あとは、価格の比較・連絡先・交渉メールまで自動で出ます。\n\n"
        "⚠️ このリストは、**ブラウザを閉じると消えます**。最後に必ず「CSVでダウンロード」で保存してください。",
        label="❓ 使い方",
    )
    st.caption("① BUYMAの商品を貼る → ② 海外のGoogleで探す → ③ 見つけたページを貼る　（※ ブラウザを閉じるとリストは消えます。CSVで保存を）")

    with st.expander("📂 前回の続きから作業する（保存したCSVを読み込む）", expanded=False):
        up = st.file_uploader("前回ダウンロードした「buyma_仕入れ先リサーチ.csv」を選んでください", type="csv", key="src_upload")
        if up is not None:
            done = st.session_state.setdefault("src_imported_ids", [])
            if up.file_id not in done:
                try:
                    n = import_sourcing_csv(up)
                    done.append(up.file_id)
                    st.success(f"{n}件を読み込みました。下の「STEP 5」に出ています。")
                except Exception as e:  # noqa: BLE001
                    st.error(f"CSVを読み込めませんでした（{e}）。ダウンロードしたCSVをそのまま選んでください。")

    # ================= STEP 1
    _head(
        "STEP 1｜売れているBUYMAの商品を読み込む",
        "ライバルが売っている（売れた）**BUYMAの商品ページのURL**を貼って「読み込む」を押します。\n\n"
        "海外ショップのURLではありません。海外ショップのURLは、STEP 3に貼ります。",
    )
    c1, c2 = st.columns([4, 1])
    with c1:
        item_url = st.text_input(
            "BUYMAの商品ページのURL", placeholder="https://www.buyma.com/item/12345678/", key="src_item_url",
        )
    with c2:
        st.write("")
        st.write("")
        load_clicked = st.button("読み込む", key="src_load", use_container_width=True, type="primary")
    if load_clicked and item_url.strip() and "buyma.com" not in item_url:
        st.error(
            "ここには **BUYMAの商品ページ**（https://www.buyma.com/item/数字/）のURLを貼ってください。"
            "海外ショップの商品ページは、下の「STEP 3」に貼ります。"
        )
    elif load_clicked and item_url.strip():
        try:
            st.session_state["src_item"] = fetch_buyma_item_info(item_url.strip())
            st.session_state.pop("src_models", None)
            st.session_state.pop("src_qsel", None)
        except Exception as e:  # noqa: BLE001
            st.error(f"商品ページを読み込めませんでした（{e}）。URLが「/item/数字/」の商品ページか確認してください。")
    item = st.session_state.get("src_item")
    if not item:
        st.caption("↑ BUYMAの商品ページのURLを貼って「読み込む」を押してください。")
    else:
        ic1, ic2, ic3 = st.columns([1, 3, 2])
        with ic1:
            if item.get("image"):
                st.image(item["image"], width=120)
        with ic2:
            st.markdown(f"**{item.get('title') or item.get('name') or '（商品名を取得できませんでした）'}**")
            st.caption(f"ブランド：{item.get('brand') or '不明'}")
        with ic3:
            if item.get("price"):
                st.metric("BUYMAでの売価", yen(item["price"]))
            else:
                p = st.number_input("BUYMAの売価（円）を入れてください", min_value=0, step=1000, key="src_price_manual")
                if p > 0:
                    item["price"] = int(p)

        # ================= STEP 2
        _head(
            "STEP 2｜海外のGoogleで、仕入れ先を探す",
            "1. 使う検索ワードを選びます（いちばん上がおすすめ）。\n"
            "2. 国のボタンを押すと、その国のGoogleの検索結果が新しいタブで開きます。\n"
            "3. 気になる商品ページを見つけたら、STEP 3に貼ります。\n\n"
            "型番や国を変えたいときは、下の「検索ワードを自分で調整する」を開いてください。",
        )
        search_box = st.container()

        brand = (item.get("brand") or "").strip()
        brand_words = [w for w in re.split(r"[\s()（）]+", brand) if w and not _JP_CHARS_RE.fullmatch(w)]
        brand_en = " ".join(brand_words) if brand_words else ""
        title_en = item.get("title_en") or ""
        cat_en = item.get("category_en") or ""
        labeled = item.get("labeled_models") or []
        guessed = [m for m in (item.get("model_candidates") or []) if m not in labeled]

        with st.expander("🔧 検索ワードを自分で調整する（型番・国を変えたいとき）"):
            e1, e2 = st.columns(2)
            with e1:
                st.markdown("**英語にしたタイトル**")
                st.code(title_en or "（英語にできませんでした）", language=None)
                st.caption(f"元のタイトル：{item.get('title') or item.get('name') or ''}")
            with e2:
                st.markdown("**ブランド・カテゴリー（英語）**")
                st.code(f"{brand_en or '（ブランド不明）'} / {cat_en or '（カテゴリー不明）'}", language=None)
                if labeled:
                    st.success("🔖 商品ページに書かれていた型番：" + "、".join(labeled))
                else:
                    st.info("商品ページには、型番の記載が見つかりませんでした。")
            picked = st.multiselect(
                "検索に使う型番（ページに書かれていたものを最初から選んでいます）", labeled + guessed,
                default=labeled[:2], key="src_models",
                help="推測の候補は、本当の型番とは限りません。検索して当たりのものを使ってください。",
            )
            extra = st.text_input("その他の検索ワード（任意）", key="src_extra", placeholder="例：PR 17ZS sunglasses black")
            countries = st.multiselect(
                "検索する国のGoogle", list(_SEARCH_COUNTRIES.keys()),
                default=["🇯🇵 日本", "🇺🇸 アメリカ", "🇬🇧 イギリス", "🇮🇹 イタリア", "🇰🇷 韓国"], key="src_countries",
            )
            use_shop = st.checkbox("ショッピング検索（価格が並ぶ画面）で開く", value=False, key="src_shop")

        queries = {}
        if brand_en and picked:
            queries["ブランド＋型番＋カテゴリー"] = " ".join(x for x in [brand_en, " ".join(picked), cat_en] if x)
        if title_en:
            queries["英語のタイトル"] = title_en
            nobrand = title_en
            for w in sorted(brand_words, key=len, reverse=True):
                nobrand = re.sub(re.escape(w), " ", nobrand, flags=re.I)
            nobrand = re.sub(r"\s+", " ", nobrand).strip()
            if nobrand and nobrand.lower() != title_en.lower() and len(nobrand) >= 4:
                queries["英語のタイトル（ブランド名なし）"] = nobrand
        for m in picked:
            queries[f"型番のみ：{m}"] = m
        if extra.strip():
            queries["その他"] = extra.strip()
        st.session_state["src_queries"] = queries

        with search_box:
            if countries and queries:
                qlabels = list(queries.keys())
                qsel = st.radio(
                    "検索ワード", qlabels, format_func=lambda k: f"{k}：{queries[k]}", key="src_qsel",
                    label_visibility="collapsed",
                )
                cols = st.columns(min(len(countries), 5))
                for n, c in enumerate(countries):
                    with cols[n % len(cols)]:
                        st.link_button(
                            f"{c} で探す", google_search_url(*_SEARCH_COUNTRIES[c][:3], queries[qsel], shopping=use_shop),
                            use_container_width=True,
                        )
            else:
                st.info("検索ワードを作れませんでした。「検索ワードを自分で調整する」を開いて、ワードを入力してください。")

            imgs = item.get("images") or ([item["image"]] if item.get("image") else [])
            if imgs:
                _head(
                    "🖼 写真でも探す（Google画像検索）",
                    "BUYMAの出品者が文字（「サイズ有り」など）を入れた写真は、ほかのショップの写真と合わず見つかりにくいので、"
                    "**加工していない白い背景の商品写真**を自動で選んでいます。別の写真に変えることもできます。\n\n"
                    "※ 見分けられるのは赤い文字の加工です。",
                    level=3,
                )
                import hashlib
                stats = score_item_images(tuple(imgs[:9]))
                rec = pick_clean_image(stats)
                itag = hashlib.md5((item.get("url") or imgs[0]).encode()).hexdigest()[:6]
                pick = st.radio(
                    "探すのに使う写真", list(range(len(stats))), index=rec, horizontal=True, key=f"src_img_{itag}",
                    format_func=lambda i: f"写真{i + 1}" + ("（おすすめ）" if i == rec else "（文字入り）" if stats[i]["edited"] else ""),
                )
                tcols = st.columns(min(len(stats), 5))
                for i, x in enumerate(stats):
                    with tcols[i % len(tcols)]:
                        st.image(x["thumb"], caption=f"写真{i + 1}" + (" ⚠️文字入り" if x["edited"] else " ⭐おすすめ" if i == rec else ""), width=110)
                st.link_button(f"🖼 写真{pick + 1}でGoogle画像検索（Lens）", img_search_url(stats[pick]["url"]))

            _head(
                "🏷 公式サイトに、まだ商品があるか確認する",
                "国のボタンを押すと、その国のGoogleで**公式サイトの中だけ**を検索します。\n\n"
                "- 商品ページが出てくれば、まだ公式にあります。\n"
                "- 出てこない・「販売終了」「在庫なし」と出る場合は、もう無い可能性があります。\n"
                "- 見つけた商品ページのURLは、STEP 3に貼ってください。「公式サイト」の印が付いて、セレクトショップと価格を比べられます。\n\n"
                "公式サイトのドメインが空のときは、ブランド名で検索します。分かったら入れてください。",
                level=3,
            )
            dom_default = official_domain_for(brand_en)
            q_default = (picked[0] if picked else (queries.get("英語のタイトル（ブランド名なし）") or queries.get("英語のタイトル") or ""))
            import hashlib
            tag = hashlib.md5(f"{brand_en}|{q_default}".encode()).hexdigest()[:6]
            o1, o2 = st.columns([2, 3])
            with o1:
                official_domain = st.text_input(
                    "公式サイトのドメイン", value=dom_default, key=f"src_off_dom_{tag}", placeholder="例）maxmara.com",
                    help="ブランドの公式サイトのアドレス（https://www. のあとの部分）です。主なブランドは自動で入ります。",
                )
            with o2:
                official_q = st.text_input(
                    "公式サイトで探すワード", value=q_default, key=f"src_off_q_{tag}",
                    help="型番が分かれば、型番がいちばん確実です。",
                )
            st.session_state["src_official_domain"] = _clean_domain(official_domain)
            off_countries = st.multiselect(
                "どの国の公式サイトで確認する？", list(_SEARCH_COUNTRIES.keys()),
                default=["🇮🇹 イタリア", "🇯🇵 日本"], key="src_off_countries",
            )
            dom = _clean_domain(official_domain)
            if off_countries and official_q.strip():
                ocols = st.columns(min(len(off_countries), 4))
                for n, c in enumerate(off_countries):
                    qq = f"site:{dom} {official_q.strip()}" if dom else f"{brand_en} official site {official_q.strip()}"
                    with ocols[n % len(ocols)]:
                        st.link_button(f"{c} の公式サイト", google_search_url(*_SEARCH_COUNTRIES[c][:3], qq), use_container_width=True)

    # ================= STEP 3
    _head(
        "STEP 3｜見つけたページを貼って、価格を読み取る",
        "Googleの検索結果で見つけた**商品ページのURL**を、1つずつ貼って「＋ 追加」を押します（Enterでも追加できます）。\n\n"
        "追加したリンクが下に並びます。間違えたら「✕」で消せます。全部入れたら「価格を読み取る」を押します。\n\n"
        "たくさんあるときは、下の「Googleの検索結果を、まるごと貼って…」に、検索結果ページの文章をまるごと貼ると、"
        "商品ページのURLを自動で取り出して追加します（トップページ・YouTube・SNS・BUYMAなどは除きます）。",
    )
    item_now = st.session_state.get("src_item") or {}
    pending = st.session_state.setdefault("src_pending_urls", [])

    def _add_pending(text: str) -> int:
        text = (text or "").strip()
        if not text:
            return 0
        if re.fullmatch(r"https?://\S+", text):
            found = [text]  # 1つだけ貼ったURLは、そのまま使う
        else:
            found = extract_urls_from_text(text)
        n = 0
        for u in found:
            if u not in pending and len(pending) < 40:
                pending.append(u)
                n += 1
        if found and not n:
            return -1  # すでに追加済み（または40件まで）
        return n

    with st.form("src_url_form", clear_on_submit=True):
        f1, f2 = st.columns([6, 1])
        with f1:
            one_url = st.text_input("商品ページのURLを、1つずつ貼る", placeholder="https://（見つけた商品ページのURL）")
        with f2:
            st.write("")
            st.write("")
            add_one = st.form_submit_button("＋ 追加", use_container_width=True)
    if add_one:
        res = _add_pending(one_url)
        if res > 0:
            st.rerun()
        elif res < 0:
            st.info("そのリンクは、すでに下の一覧に入っています（40件までです）。")
        else:
            st.warning("URLが見つかりませんでした。「https://」から始まるURLを貼ってください。")

    if pending:
        st.markdown(f"**追加したリンク（{len(pending)}件）**")
        for i, u in enumerate(list(pending)):
            l1, l2 = st.columns([12, 1])
            with l1:
                st.markdown(f"{i + 1}. [{u[:90] + '…' if len(u) > 90 else u}]({u})")
            with l2:
                if st.button("✕", key=f"src_pend_del_{i}_{abs(hash(u)) % 10**6}", help="このリンクを消す"):
                    pending.remove(u)
                    st.rerun()
        if st.button(f"価格を読み取る（{len(pending)}件）", key="src_bulk_go", type="primary"):
            urls = list(pending)
            with st.spinner(f"{len(urls)}件の商品ページを読み取り中…"):
                prev = st.session_state.get("src_candidates") or []
                new_rows = _run_parallel(analyze_supplier_safe, urls)
                merged = {r["仕入れ先URL"]: r for r in prev}
                merged.update({r["仕入れ先URL"]: r for r in new_rows})
                st.session_state["src_candidates"] = list(merged.values())
            st.session_state["src_pending_urls"] = []
            st.session_state["src_read_msg"] = f"{len(urls)}件のページを読み取りました。下の「STEP 4」を見てください。"
            st.rerun()
    if st.session_state.get("src_read_msg"):
        st.success(st.session_state.pop("src_read_msg"))

    with st.expander("📋 Googleの検索結果を、まるごと貼って一度に追加する"):
        bulk_text = st.text_area("検索結果の文章（command+A → command+C でコピーしたもの）", height=120, key="src_bulk", placeholder="ここに貼り付け")
        if st.button("検索結果からリンクを取り出して追加", key="src_bulk_add"):
            res = _add_pending(bulk_text)
            if res > 0:
                st.rerun()
            elif res < 0:
                st.info("見つかったリンクは、すでに一覧に入っています。")
            else:
                st.warning("商品ページのURLが見つかりませんでした。検索結果のページを全選択してコピーしたものを貼ってください。")

    with st.expander("🔧 上級：ショップのトップページから、商品を自動で探す（Shopify製のショップのみ）"):
        shops_text = st.text_area("ショップのURL（1行に1つ）", height=80, key="src_shops",
                                  placeholder="https://www.aloyoga.com\nhttps://www.kith.com")
        if st.button("ショップ内を検索して候補を集める", key="src_shop_go"):
            shops = [x.strip() for x in shops_text.splitlines() if x.strip()]
            allq = st.session_state.get("src_queries") or {}
            order = ["商品名（ブランド名なし）", "商品名（英数字のみ）"]
            qs = [allq[k] for k in order if k in allq] + [q for k, q in allq.items() if k.startswith(("ブランド＋型番", "型番のみ"))]
            qs = list(dict.fromkeys(qs))[:4]
            if not shops or not qs:
                st.warning("ショップのURLと、STEP 2の検索ワードが必要です（BUYMAの商品を読み込むと自動で作られます）。")
            else:
                with st.spinner("各ショップの中を検索しています…"):
                    urls, unsupported = [], []
                    for shop in shops:
                        found_any = False
                        for q in qs:
                            hits = search_shopify_store(shop, q)
                            if hits is None:
                                break
                            found_any = True
                            urls.extend(hits)
                        if not found_any:
                            unsupported.append(shop)
                    urls = list(dict.fromkeys(urls))[:40]
                    rows = _run_parallel(analyze_supplier_safe, urls) if urls else []
                prev = st.session_state.get("src_candidates") or []
                merged = {r["仕入れ先URL"]: r for r in prev}
                merged.update({r["仕入れ先URL"]: r for r in rows})
                st.session_state["src_candidates"] = list(merged.values())
                if unsupported:
                    st.warning("自動検索に対応していないショップ：" + "、".join(unsupported) + "（商品ページのURLを上の欄に貼ってください）")
                if not urls:
                    st.info("検索ワードに当てはまる商品が見つかりませんでした。検索ワードを変えて試してください。")

    # ================= STEP 4
    cands = st.session_state.get("src_candidates") or []
    if cands:
        _head(
            "STEP 4｜価格を比べる",
            "**BUYMAの売価 − 仕入れ値 ＝ 差額** を、仕入れ先ごとに出します。\n\n"
            "- この差額から、BUYMA手数料・国際送料・関税・国内送料を引いたものが、実際の利益です。\n"
            "- 「海外の消費税」は、表示価格にVATが含まれているかです。日本向けに免税になれば、その分安くなります"
            "（免税になるかは、ショップに確認が必要です）。\n"
            "- 🏷公式＝ブランドの公式サイト、セレクト＝セレクトショップなどです。\n\n"
            "**自動で価格を読めなかった行**は、表の「✏️ 価格を手入力」をダブルクリックして、ページで見た価格を入れます（Enterで反映）。"
            "**先に右の「通貨」が合っているか確認してください**（イタリアならEUR、アメリカならUSDなど）。",
        )
        _render_candidates(cands, item_now)

    rows = _sourcing_rows()
    if not rows:
        if not cands:
            st.caption("まだ仕入れ先がありません。STEP 3で、見つけたページを貼ってください。")
        return
    _render_sourcing_list_and_detail(rows)


def _render_candidates(cands: list, item_now: dict):
    import hashlib

    yens = sorted(int(float(c["円換算"])) for c in cands if _has_yen(c))
    buyma_price = int(item_now.get("price") or 0)
    bad = [c for c in cands if not _has_yen(c)]

    if st.session_state.get("src_fix_msg"):
        st.success(st.session_state.pop("src_fix_msg"))

    if yens:
        if buyma_price:
            gap = buyma_price - yens[0]
            msg = (
                f"### BUYMAの売価 {yen(buyma_price)} − 一番安い仕入れ先 {yen(yens[0])} ＝ **{_signed_yen(gap)}**\n\n"
                f"売価の約 {gap / buyma_price * 100:.0f}% の差があります。"
                if gap > 0 else
                f"### BUYMAの売価 {yen(buyma_price)} − 一番安い仕入れ先 {yen(yens[0])} ＝ **{_signed_yen(gap)}**\n\n"
                "仕入れ値のほうが高く、このままでは赤字です。"
            )
            vf_all = [v for v in (vat_free_yen(c.get("円換算"), c.get("VAT表示"), c.get("VAT率")) for c in cands if _has_yen(c)) if v]
            if vf_all and min(vf_all) < yens[0]:
                msg += f"\n\n💡 VATが免税なら、最安 {yen(min(vf_all))} → 差額 {_signed_yen(buyma_price - min(vf_all))}"
            (st.success if gap > 0 else st.error)(msg)
        else:
            st.info("上のSTEP 1でBUYMAの商品を読み込むと、「BUYMAの売価との差」がここに出ます。")

    off_dom = st.session_state.get("src_official_domain", "")
    if off_dom:
        off_y = [int(float(c["円換算"])) for c in cands if _has_yen(c) and _site_kind(c["仕入れ先URL"]) == "公式サイト"]
        sel_y = [int(float(c["円換算"])) for c in cands if _has_yen(c) and _site_kind(c["仕入れ先URL"]) != "公式サイト"]
        if off_y and sel_y:
            o, sm = min(off_y), min(sel_y)
            diff = o - sm
            word = f"セレクトショップのほうが **{yen(abs(diff))}（{abs(diff) / o * 100:.0f}%）安い**" if diff > 0 else (
                f"公式サイトのほうが **{yen(abs(diff))}（{abs(diff) / sm * 100:.0f}%）安い**" if diff < 0 else "同じ価格")
            st.info(f"🏷 **公式サイト {yen(o)}**　と　**セレクトショップ最安 {yen(sm)}**　を比べると、{word}です。")
        elif off_y:
            st.info(f"🏷 公式サイトの価格：{yen(min(off_y))}。セレクトショップの価格を、STEP 3で貼ると比べられます。")
        elif any(_site_kind(c["仕入れ先URL"]) == "公式サイト" for c in cands):
            st.warning("🏷 公式サイトのページは見つかりましたが、価格を読めていません。下の「手伝ってください」で価格を入れてください。")
        else:
            st.caption("🏷 公式サイトの価格は、まだありません。")

    if bad:
        with st.expander(f"⚠️ 価格を読めなかったページ {len(bad)}件（手伝ってください）", expanded=True):
            h1, h2 = st.columns([5, 1])
            with h1:
                st.caption("ツールからは読めませんでした。ページを開いて、AかBのどちらかで入れてください。")
            with h2:
                with st.popover("❓ やり方", use_container_width=True):
                    st.markdown(
                        "サイトがロボットのアクセスを断っているため、ツールからは読めません。でも、**あなたのブラウザでは開けます**。\n\n"
                        "1. 「🔗 ページを開く」で、そのページを開く\n"
                        "2. **A**：ページを全選択（command+A）→ コピー（command+C）→ 「A」の欄に貼る\n"
                        "3. **B**：ページで価格を見て、「B」の欄に自分で入れる\n"
                        "4. 「反映する」を押す → 日本円・VAT・価格差を計算します\n\n"
                        "表の「✏️ 価格を手入力」に直接入れてもOKです。"
                    )
            for c in bad:
                url = c["仕入れ先URL"]
                key = hashlib.md5(url.encode()).hexdigest()[:8]
                st.markdown(f"**{c.get('仕入れ先サイト')}**　`{url[:70]}…`" if len(url) > 70 else f"**{c.get('仕入れ先サイト')}**　`{url}`")
                st.link_button("🔗 ページを開く", url)
                with st.form(f"src_fix_{key}"):
                    f1, f2, f3 = st.columns([3, 2, 1])
                    with f1:
                        ptxt = st.text_area("A：ページの文字を貼る", height=80, key=f"src_fix_text_{key}")
                    with f2:
                        pamt = st.number_input("B：価格（現地の金額）", min_value=0.0, step=1.0, key=f"src_fix_amt_{key}")
                    with f3:
                        pcur = st.selectbox("通貨", _CURRENCY_CHOICES, key=f"src_fix_cur_{key}")
                    if st.form_submit_button("反映する"):
                        amount, cur, note = None, pcur, ""
                        if pamt > 0:
                            amount = float(pamt)
                        elif ptxt.strip():
                            found = find_prices_in_text(ptxt, yen_is_jpy=_guess_currency(url) == "JPY" or "ZOZOTOWN" in ptxt)
                            if found:
                                amount, cur = found[0]
                                note = "（貼ったページから見つけた価格：" + "、".join(f"{a:,.2f} {cu}" for a, cu in found[:4]) + "。違う場合は、Bに入れ直してください）"
                        if amount:
                            new = fill_supplier_price(c, amount, cur, ptxt)
                            ex = parse_pasted_extras(ptxt)
                            if ex["stock"]:
                                new["在庫（サイズ別）"] = ex["stock"]
                            if ex["info"]:
                                new["ショップ情報"] = "\n".join(ex["info"])
                            if ex["title"]:
                                new["仕入れ先商品名"] = ex["title"]
                            st.session_state["src_candidates"] = [new if x["仕入れ先URL"] == url else x for x in st.session_state["src_candidates"]]
                            st.session_state["src_fix_msg"] = f"{c.get('仕入れ先サイト')}：{amount:,.2f} {cur} で反映しました。{note}"
                            st.rerun()
                        else:
                            st.warning("価格を見つけられませんでした。Bに価格を入れてください。")

    show_all = st.checkbox("くわしい列（VAT抜きの金額・在庫）も表示する", value=False, key="src_cand_all")
    cdf = pd.DataFrame(cands)
    cdf["_y"] = pd.to_numeric(cdf["円換算"], errors="coerce")
    cdf = cdf.sort_values("_y", na_position="last").drop(columns="_y").reset_index(drop=True)
    cdf.insert(0, "追加", False)
    cdf["円換算"] = pd.to_numeric(cdf["円換算"], errors="coerce")
    cdf["現地の価格"] = [
        f"{float(r['現地価格']):,.0f} {r['通貨']}" if str(r.get("現地価格") or "").strip() not in ("", "nan") else "（読めず）"
        for r in cdf.to_dict("records")
    ]
    cdf["VAT抜き円換算"] = pd.to_numeric(
        [vat_free_yen(r.get("円換算"), r.get("VAT表示"), r.get("VAT率")) for r in cdf.to_dict("records")], errors="coerce"
    )
    cdf["種類"] = [("🏷 公式" if _site_kind(u) == "公式サイト" else "セレクト") for u in cdf["仕入れ先URL"]]
    cdf["VAT表示"] = [
        "🇺🇸 VATなし（抜けません）" if str(c) == "USD" else v for v, c in zip(cdf["VAT表示"], cdf["通貨"])
    ]  # アメリカのサイト（ドル表示）は、VATがないので抜けない（表示だけの変更。保存データは変えない）
    cdf["手入力の価格"] = float("nan")
    cdf["手入力の通貨"] = [_guess_currency(u) for u in cdf["仕入れ先URL"]]
    show_cols = ["追加", "種類", "仕入れ先サイト", "仕入れ先商品名", "現地の価格", "手入力の価格", "手入力の通貨", "円換算"]
    if buyma_price:
        cdf["BUYMA売価"] = buyma_price
        cdf["売価−仕入れの差額"] = buyma_price - cdf["円換算"]
        cdf["差額の割合"] = (cdf["売価−仕入れの差額"] / buyma_price * 100).round(1)
        cdf["VAT抜きの場合の差額"] = buyma_price - cdf["VAT抜き円換算"]
        show_cols += ["BUYMA売価", "売価−仕入れの差額", "差額の割合"]
    show_cols += ["VAT表示"]
    if show_all:
        show_cols += ["VAT抜き円換算"] + (["VAT抜きの場合の差額"] if buyma_price else []) + ["在庫（サイズ別）"]
    show_cols += ["仕入れ先URL"]
    ver = st.session_state.get("src_cand_ver", 0)
    picked_df = st.data_editor(
        cdf[show_cols], use_container_width=True, hide_index=True, key=f"src_cand_editor_{ver}",
        disabled=[c for c in show_cols if c not in ("追加", "手入力の価格", "手入力の通貨")],
        column_config={
            "追加": st.column_config.CheckboxColumn("追加", help="気になる仕入れ先にチェック → 下のボタンで、STEP 5のリストに入ります"),
            "手入力の価格": st.column_config.NumberColumn(
                "✏️ 価格を手入力", min_value=0.0, format="%.2f",
                help="自動で読めなかったときは、ここに商品ページで見た価格（現地の金額）を入れてください。入れると、日本円・差額を計算します。",
            ),
            "手入力の通貨": st.column_config.SelectboxColumn("通貨", options=_CURRENCY_CHOICES, help="手入力した価格の通貨（国から推測しています）"),
            "種類": st.column_config.TextColumn("種類", help="🏷公式＝ブランドの公式サイト／セレクト＝セレクトショップなど"),
            "仕入れ先サイト": st.column_config.TextColumn("ショップ"),
            "仕入れ先商品名": st.column_config.TextColumn("商品名"),
            "円換算": st.column_config.NumberColumn("日本円で", format="yen", help="為替レートで日本円にした金額（目安）"),
            "BUYMA売価": st.column_config.NumberColumn("ライバルの売価（BUYMA）", format="yen", help="BUYMAで売れている商品の販売価格"),
            "売価−仕入れの差額": st.column_config.NumberColumn("差額（売価−仕入れ）", format="yen", help="BUYMAの売価 − 仕入れ値。手数料・送料・関税は含みません"),
            "差額の割合": st.column_config.NumberColumn("差額の割合", format="%.1f%%", help="差額 ÷ BUYMAの売価"),
            "VAT表示": st.column_config.TextColumn("海外の消費税", help="表示価格に海外の消費税（VAT）が含まれているか。「推定」は国の傾向からの推測です"),
            "VAT抜き円換算": st.column_config.NumberColumn("VAT抜きで", format="yen", help="VATが免税になった場合の目安（会計時に必ず確認）"),
            "VAT抜きの場合の差額": st.column_config.NumberColumn("VAT抜きの差額", format="yen", help="BUYMAの売価 − VAT抜きの仕入れ額"),
            "仕入れ先URL": st.column_config.LinkColumn("商品ページ", display_text="🔗 開く"),
        },
    )
    typed = picked_df[picked_df["手入力の価格"].fillna(0) > 0]
    if len(typed):
        by_u = {c["仕入れ先URL"]: c for c in st.session_state["src_candidates"]}
        for _, tr in typed.iterrows():
            base = by_u.get(tr["仕入れ先URL"])
            if base:
                by_u[tr["仕入れ先URL"]] = fill_supplier_price(base, float(tr["手入力の価格"]), tr["手入力の通貨"] or _guess_currency(tr["仕入れ先URL"]))
        st.session_state["src_candidates"] = list(by_u.values())
        st.session_state["src_cand_ver"] = ver + 1
        st.session_state["src_fix_msg"] = f"{len(typed)}件の価格を反映しました。"
        st.rerun()
    st.caption("✏️ 読めなかった行は、「価格を手入力」をダブルクリックして入力（先に「通貨」を確認）")
    chosen = picked_df[picked_df["追加"]]["仕入れ先URL"].tolist()
    b1, b2 = st.columns([3, 1])
    with b1:
        if st.button(f"✅ チェックした {len(chosen)} 件を、STEP 5のリストに追加（連絡先も調べます）", key="src_cand_add", disabled=not chosen, type="primary"):
            with st.spinner("連絡先・在庫を調べています…"):
                by_url = {c["仕入れ先URL"]: c for c in cands}
                full = _run_parallel(
                    lambda u: by_url[u] if (by_url[u].get("_manual") or not _has_yen(by_url[u])) else analyze_supplier_safe(u, light=False),
                    chosen,
                )
            n = 0
            for row in full:
                row = {k: v for k, v in row.items() if k != "_manual"}
                n = _add_sourcing_row(row, item_now)
            st.success(f"追加しました（現在 {n} 件）。下の「STEP 5」を見てください。")
    with b2:
        if st.button("候補を全部消す", key="src_cand_clear", use_container_width=True):
            st.session_state["src_candidates"] = []
            st.rerun()


def _render_sourcing_list_and_detail(rows: list):
    import hashlib
    # ================= STEP 5
    _head(
        "STEP 5｜保存した仕入れ先リスト",
        "交渉・問い合わせをしたら「交渉済み」にチェックします。\n\n"
        "メモ（改行できます）とリンクは、下の **STEP 6** で書けます。\n\n"
        "最後に「CSVでダウンロード」で保存してください（ブラウザを閉じるとリストは消えます）。",
    )
    df = pd.DataFrame(rows).reindex(columns=SOURCING_COLUMNS)
    df["交渉済み"] = df["交渉済み"].fillna(False).astype(bool)
    for _c in ("追加日時", "BUYMA商品名", "仕入れ先サイト", "種類", "仕入れ先商品名", "通貨", "VAT表示", "VAT根拠", "在庫（サイズ別）",
               "電話", "メール", "問い合わせページ", "仕入れ先URL", "BUYMA商品URL", "メモ", "リンク集", "ショップ情報"):
        df[_c] = df[_c].fillna("").astype(str).replace("nan", "")
    _b = pd.to_numeric(df["BUYMA売価"], errors="coerce")
    _y = pd.to_numeric(df["円換算"], errors="coerce")
    df.insert(df.columns.get_loc("円換算") + 1, "売価−仕入れの差額", _b - _y)
    df.insert(df.columns.get_loc("売価−仕入れの差額") + 1, "差額の割合", ((_b - _y) / _b * 100).round(1))
    _vf = pd.Series([vat_free_yen(r.get("円換算"), r.get("VAT表示"), r.get("VAT率")) for r in df.to_dict("records")], index=df.index)
    _vf = pd.to_numeric(_vf, errors="coerce")
    df.insert(df.columns.get_loc("差額の割合") + 1, "VAT抜き円換算", _vf)
    df.insert(df.columns.get_loc("VAT抜き円換算") + 1, "VAT抜きの場合の差額", _b - _vf)
    show_all = st.checkbox("すべての列を表示する（くわしく見たいとき）", value=False, key="src_list_all")
    simple = ["交渉済み", "種類", "仕入れ先サイト", "仕入れ先商品名", "円換算", "BUYMA売価", "売価−仕入れの差額", "差額の割合", "VAT表示", "仕入れ先URL", "メモ"]
    edited = st.data_editor(
        df, use_container_width=True, hide_index=True, key="src_editor",
        column_order=None if show_all else simple,
        disabled=[c for c in df.columns if c != "交渉済み"],
        column_config={
            "交渉済み": st.column_config.CheckboxColumn("交渉済み", help="交渉・問い合わせをしたらチェック"),
            "種類": st.column_config.TextColumn("種類"),
            "仕入れ先サイト": st.column_config.TextColumn("ショップ"),
            "仕入れ先商品名": st.column_config.TextColumn("商品名"),
            "BUYMA売価": st.column_config.NumberColumn("ライバルの売価（BUYMA）", format="yen"),
            "円換算": st.column_config.NumberColumn("日本円で", format="yen"),
            "売価−仕入れの差額": st.column_config.NumberColumn("差額（売価−仕入れ）", format="yen", help="BUYMAの売価 − 仕入れ値（日本円）。手数料・送料・関税は含みません"),
            "差額の割合": st.column_config.NumberColumn("差額の割合", format="%.1f%%"),
            "VAT表示": st.column_config.TextColumn("海外の消費税"),
            "VAT抜き円換算": st.column_config.NumberColumn("VAT抜きで", format="yen", help="VATを除いた場合の想定の仕入れ額（目安）"),
            "VAT抜きの場合の差額": st.column_config.NumberColumn("VAT抜きの差額", format="yen", help="BUYMAの売価 − VAT抜きの仕入れ額"),
            "問い合わせページ": st.column_config.LinkColumn("問い合わせページ", display_text="🔗 開く"),
            "仕入れ先URL": st.column_config.LinkColumn("商品ページ", display_text="🔗 開く"),
            "BUYMA商品URL": st.column_config.LinkColumn("BUYMA商品URL", display_text="🔗 開く"),
            "メモ": st.column_config.TextColumn("メモ", help="メモは STEP 6 で書けます（改行もできます）"),
        },
    )
    st.session_state["sourcing_list"] = edited[SOURCING_COLUMNS].to_dict("records")

    cc1, cc2 = st.columns(2)
    with cc1:
        csv = edited[SOURCING_COLUMNS].to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 CSVでダウンロード（保存・スプレッドシート用）", data=csv,
            file_name="buyma_仕入れ先リサーチ.csv", mime="text/csv", use_container_width=True, type="primary",
        )
    with cc2:
        if st.button("🗑 リストを空にする", key="src_clear", use_container_width=True):
            st.session_state["sourcing_list"] = []
            st.rerun()

    # ================= STEP 6
    _head(
        "STEP 6｜選んだ仕入れ先に連絡する",
        "仕入れ先を選ぶと、在庫・連絡先・メモ・リンク・交渉メールの例文が出ます。\n\n"
        "メモは改行できます。リンクは1つずつ追加できます（公式サイト、別のショップ、在庫確認ページなど）。",
    )
    labels = [f"{r.get('仕入れ先サイト') or '?'}｜{(r.get('仕入れ先商品名') or '')[:30]}" for r in edited.to_dict("records")]
    idx = st.selectbox("どの仕入れ先に連絡しますか？", range(len(labels)), format_func=lambda i: labels[i], key="src_pick")
    r = edited.to_dict("records")[idx]

    d1, d2 = st.columns(2)
    with d1:
        st.markdown("**在庫（サイズ別）**")
        stock = str(r.get("在庫（サイズ別）") or "")
        if "✅" in stock or "❌" in stock:
            for part in stock.split("、"):
                st.markdown(f"- {part}")
        else:
            st.caption(stock or "取得できず")
        if r.get("現地価格") not in ("", None):
            st.markdown(f"**価格**：{r.get('現地価格')} {r.get('通貨')}（約{yen(r['円換算']) if r.get('円換算') not in ('', None) else '円換算できず'}）")
    with d2:
        st.markdown("**連絡先**")
        for ph in [p for p in str(r.get("電話") or "").split(" / ") if p]:
            st.markdown(f"- 📞 [{ph}](tel:{ph})")
        for em in [e for e in str(r.get("メール") or "").split(" / ") if e]:
            st.markdown(f"- ✉️ [{em}](mailto:{em})")
        if r.get("問い合わせページ"):
            st.link_button("💬 問い合わせページを開く", r["問い合わせページ"])
        if not (r.get("電話") or r.get("メール") or r.get("問い合わせページ")):
            st.caption("連絡先を自動では見つけられませんでした。")
        shop_info = str(r.get("ショップ情報") or "")
        shop_name = ""
        for ln in shop_info.split("\n"):
            if ln.startswith("ショップ："):
                shop_name = re.split(r"[（(]", ln[len("ショップ："):])[0].strip()
        if shop_info or shop_name:
            st.markdown("**🏬 ショップ情報**")
            for ln in shop_info.split("\n"):
                if ln.strip():
                    st.markdown(f"- {ln}")
        _u = str(r.get("仕入れ先URL") or "")
        _zm = re.search(r"zozo\.jp/shop/([^/]+)/", _u)
        if _zm:  # ZOZOTOWNは、ショップ名がURLに入っている（例：/shop/soph/）
            st.link_button("🏬 ZOZOTOWNの「ショップ紹介」ページを開く", f"https://zozo.jp/shop/{_zm.group(1)}/detail/", use_container_width=True)
        _site = str(r.get("仕入れ先サイト") or "")
        _default_name = shop_name or (_zm.group(1).upper() if _zm else _site)
        _ctag = hashlib.md5(_u.encode()).hexdigest()[:8]
        sq = st.text_input(
            "ショップ名（検索に使います。違うときは直してください）", value=_default_name, key=f"src_shopname_{_ctag}",
        ).strip()
        if sq:
            q1, q2 = st.columns(2)
            with q1:
                st.link_button(f"🔍 「{sq[:14]}」の店舗を調べる", f"https://www.google.co.jp/search?q={quote_plus(sq + ' 店舗 実店舗')}", use_container_width=True)
            with q2:
                st.link_button(f"🔍 「{sq[:14]}」の公式サイト", f"https://www.google.co.jp/search?q={quote_plus(sq + ' 公式サイト')}", use_container_width=True)
        with st.expander("📋 ショップ情報のページの文字を貼って、連絡先を読み取る"):
            st.caption("ZOZOTOWNなど、ツールから読めないサイトで使います。")
            si_key = f"src_shopinfo_{hashlib.md5(str(r.get('仕入れ先URL') or idx).encode()).hexdigest()[:8]}"
            with st.popover("❓ やり方"):
                st.markdown(
                    "1. ブラウザで、そのショップの**「ショップ情報」「特定商取引法に基づく表記」「会社概要」**などのページを開く\n"
                    "2. **command+A** で全選択 → **command+C** でコピー\n"
                    "3. 下の欄に貼って「読み取る」を押す\n\n"
                    "電話・メール・会社名・所在地などを、自動で拾います。"
                )
            info_text = st.text_area("ショップ情報のページの文字", height=120, key=si_key + "_t")
            if st.button("読み取る", key=si_key + "_b"):
                got = parse_shop_info(info_text)
                if not (got["phones"] or got["emails"] or got["fields"]) and info_text.strip():
                    st.session_state["sourcing_list"][idx]["ショップ情報"] = "紹介：" + re.sub(r"\s+", " ", info_text.strip())[:200]
                    st.rerun()
                elif not (got["phones"] or got["emails"] or got["fields"]):
                    st.warning("貼り付ける文字がありません。ページを全選択してコピーしたものを貼ってください。")
                else:
                    row = st.session_state["sourcing_list"][idx]
                    old_p = [x for x in str(row.get("電話") or "").split(" / ") if x]
                    old_m = [x for x in str(row.get("メール") or "").split(" / ") if x]
                    row["電話"] = " / ".join(dict.fromkeys(old_p + got["phones"]))
                    row["メール"] = " / ".join(dict.fromkeys(old_m + got["emails"]))
                    row["ショップ情報"] = "\n".join(f"{k}：{v}" for k, v in got["fields"].items())
                    st.rerun()

    tag = hashlib.md5(str(r.get("仕入れ先URL") or idx).encode()).hexdigest()[:8]
    st.markdown("**📝 メモ**")
    memo_key = f"src_memo_{tag}"
    st.text_area(
        "メモ（Enterで改行できます。書いたら、欄の外をクリックで保存）", value=str(r.get("メモ") or ""), height=150, key=memo_key,
        on_change=_set_sourcing_field, args=(idx, "メモ", memo_key),
        placeholder="例）\nサイズM 在庫あり\n送料 ¥3,000\n返信待ち 10/8",
    )
    st.markdown("**🔗 リンク**")
    links = [ln for ln in str(r.get("リンク集") or "").split("\n") if ln.strip()]
    for i, ln in enumerate(links):
        name, _, u = ln.partition("｜") if "｜" in ln else ("", "", ln)
        l1, l2 = st.columns([9, 1])
        with l1:
            st.markdown(f"- [{name or u}]({u})")
        with l2:
            if st.button("✕", key=f"src_linkdel_{tag}_{i}", help="このリンクを消す"):
                new_links = [x for j, x in enumerate(links) if j != i]
                st.session_state["sourcing_list"][idx]["リンク集"] = "\n".join(new_links)
                st.rerun()
    with st.form(f"src_linkform_{tag}", clear_on_submit=True):
        f1, f2 = st.columns([2, 5])
        with f1:
            lname = st.text_input("名前（任意）", placeholder="例）公式サイト")
        with f2:
            lurl = st.text_input("リンクを1つ入れる", placeholder="https://")
        if st.form_submit_button("＋ リンクを追加"):
            if lurl.strip():
                entry = f"{lname.strip()}｜{lurl.strip()}" if lname.strip() else lurl.strip()
                st.session_state["sourcing_list"][idx]["リンク集"] = "\n".join(links + [entry])
                st.rerun()

    is_jp = _is_japan_shop(r)
    if is_jp:
        st.info(
            "🇯🇵 日本のショップです。海外向けの交渉メールや、海外の消費税（VAT）の確認は、ふつう要りません。"
            "上の電話・メール・問い合わせページで、在庫や価格を確認してください。"
        )
        if not st.checkbox("海外向けの交渉メールの例文も表示する", value=False, key="src_show_mail"):
            return
    else:
        vf = vat_free_yen(r.get("円換算"), r.get("VAT表示"), r.get("VAT率"))
        with st.expander("💶 海外の消費税（VAT）はどうなる？", expanded=vf is not None):
            with st.popover("❓ 解説"):
                st.markdown(
                    "海外のショップは、日本へ送るとき**海外の消費税（VAT）を免税にしてくれることがあります**。免税になれば、その分、仕入れが安くなります。\n\n"
                    "ここに出る「VAT抜き」の金額は、**会計時にVATが免税になる場合の目安**です。実際に免税になるかは、"
                    "ショップのレジで日本の住所を入れるか、下のメールで確認してください。VAT率は国の標準税率の目安で、商品によって違うことがあります。"
                )
            _opts = ["（国を選ぶ）"] + list(_VAT_COUNTRIES)
            _tld = urlparse(str(r.get("仕入れ先URL") or "")).netloc.lower().rsplit(".", 1)[-1]
            _guess = _TLD_VAT_COUNTRY.get(_tld) or {
                "USD": "🇺🇸 アメリカ（VATなし）", "GBP": "🇬🇧 イギリス", "KRW": "🇰🇷 韓国", "AUD": "🇦🇺 オーストラリア", "CAD": "🇨🇦 カナダ（GST）",
            }.get(str(r.get("通貨") or ""))
            if st.session_state.get(f"src_vat_country_{tag}", _guess) == "🇺🇸 アメリカ（VATなし）":
                st.error(
                    "### 🇺🇸 アメリカのサイトは、VATを抜けません\n\n"
                    "アメリカには、ヨーロッパのようなVAT（付加価値税）がありません。**表示価格が、そのまま仕入れ額**です（送料・関税は別）。"
                )
            v0, v1, v2 = st.columns(3)
            with v0:
                st.selectbox(
                    "ショップの国", _opts, index=_opts.index(_guess) if _guess in _opts else 0, key=f"src_vat_country_{tag}",
                    on_change=_set_vat_country, args=(idx, f"src_vat_country_{tag}", f"src_vat_rate_{tag}"),
                    help="国を選ぶと、その国の標準的なVAT率が「VAT率」に自動で入ります。",
                )
            with v1:
                cur_status = r.get("VAT表示") if r.get("VAT表示") in _VAT_STATUSES else "不明"
                st.selectbox(
                    "表示価格の税", _VAT_STATUSES, index=_VAT_STATUSES.index(cur_status), key=f"src_vat_status_{tag}",
                    on_change=_set_sourcing_field, args=(idx, "VAT表示", f"src_vat_status_{tag}"),
                    help="ページの記載から自動判定しています。実際と違う場合は、ここで直してください。",
                )
            with v2:
                try:
                    cur_rate = float(r.get("VAT率")) if r.get("VAT率") not in ("", None) else 0.0
                except (TypeError, ValueError):
                    cur_rate = 0.0
                st.number_input(
                    "VAT率（%）", min_value=0.0, max_value=40.0, value=cur_rate, step=0.5, key=f"src_vat_rate_{tag}",
                    on_change=_set_sourcing_field, args=(idx, "VAT率", f"src_vat_rate_{tag}"),
                    help="国の標準的な税率の目安を入れています。分かる場合は直してください。",
                )
            try:
                _d, _rt = int(float(r["円換算"])), float(r.get("VAT率") or 0)
            except (TypeError, ValueError):
                _d, _rt = None, 0.0
            if _d is not None:
                if r.get("VAT表示") == "税抜き":
                    _inc, _exc = int(round(_d * (1 + _rt / 100))), _d
                else:
                    _inc, _exc = _d, int(round(_d / (1 + _rt / 100))) if _rt > 0 else _d
                _bp = int(r["BUYMA売価"]) if r.get("BUYMA売価") not in ("", None) else None
                k1, k2 = st.columns(2)
                with k1:
                    st.metric(f"VAT込みの仕入れ額（VAT{_rt:g}%を払う場合）", yen(_inc))
                    if _bp:
                        st.caption(f"差額（売価−仕入れ）：{_signed_yen(_bp - _inc)}")
                with k2:
                    st.metric("VAT抜きの仕入れ額（免税になる場合）", yen(_exc))
                    if _bp:
                        st.caption(f"差額（売価−仕入れ）：{_signed_yen(_bp - _exc)}")
                st.caption(f"お店の表示価格 {yen(_d)} は「{r.get('VAT表示') or '不明'}」の金額です。国を選ぶと、VAT率が変わって、上の金額が変わります。")
            st.caption(f"判定の根拠：{r.get('VAT根拠') or '（なし）'}")


    m1, m2 = st.columns([5, 1])
    with m1:
        st.markdown("**✉️ 交渉メールの例文**")
    with m2:
        with st.popover("❓ 解説", use_container_width=True):
            st.markdown(
                "文章の右上のコピーボタンでコピーできます。\n\n"
                "例文は自動で作った文章です。送る前に、内容（特に免税インボイスや支払い方法の条件）を確認してください。"
            )
    t1, t2, t3 = st.columns(3)
    with t1:
        lang = st.selectbox("言語", list(_NEGOTIATION_TEMPLATES.keys()), key="src_lang")
    with t2:
        qty = st.text_input("希望サイズ・数量", value="例）S x1, M x2", key="src_qty")
    with t3:
        sender = st.text_input("あなたの名前・屋号", key="src_sender", placeholder="例）Naoko / ○○ Store")
    product_name = (r.get("仕入れ先商品名") or r.get("BUYMA商品名") or "").strip()
    body = _NEGOTIATION_TEMPLATES[lang].format(
        product=product_name, url=r.get("仕入れ先URL") or "", qty=qty, sender=sender or "（名前）",
    )
    st.code(body, language=None)
    with st.expander("日本語訳で内容を確認する"):
        st.text(_NEGOTIATION_JA)


# ============================ エントリーポイント ============================
def main():
    tab1, tab2, tab3, tab4 = st.tabs([
        "🔎 出品者チェック", "💰 商品ごとの価格チェック", "🛒 仕入れ先リサーチ", "📒 ブランド候補リスト",
    ])
    with tab1:
        render_seller_tool()
    with tab2:
        render_price_tool()
    with tab3:
        render_sourcing_tool()
    with tab4:
        render_watchlist_tool()


if __name__ == "__main__":
    main()
