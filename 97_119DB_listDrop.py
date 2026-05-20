import streamlit as st
import pandas as pd
import io
import requests
from PIL import Image
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.utils import ImageReader
import time
from pathlib import Path
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
import re

# =========================================================
# フォント設定
# =========================================================
def _setup_font():

    here = Path(__file__).parent

    candidates = [
        here / "fonts" / "IPAexGothic.ttf",
        here / "IPAexGothic.ttf",
        Path.cwd() / "fonts" / "IPAexGothic.ttf",
        Path.cwd() / "IPAexGothic.ttf",
    ]

    for p in candidates:

        if p.exists():

            pdfmetrics.registerFont(
                TTFont("Japanese", str(p))
            )

            return "Japanese"

    pdfmetrics.registerFont(
        UnicodeCIDFont("HeiseiKakuGo-W5")
    )

    return "HeiseiKakuGo-W5"

JAPANESE_FONT = _setup_font()

# =========================================================
# Streamlit設定
# =========================================================
st.set_page_config(
    page_title="🔍 学生指導用データベース",
    layout="wide"
)

st.title("🔍 LIST_drop_to_DB歯科医師国家試験97_119")

# =========================================================
# SessionState
# =========================================================
if "pdf_bytes" not in st.session_state:
    st.session_state["pdf_bytes"] = None

# =========================================================
# 列名正規化
# =========================================================
def normalize_columns(df: pd.DataFrame):

    def _clean(s):

        s = str(s).replace("\ufeff", "")

        return re.sub(
            r"[\u3000 \t\r\n]+",
            "",
            s
        )

    df = df.copy()

    df.columns = [_clean(c) for c in df.columns]

    alias = {
        "問題文": ["設問", "問題", "本文"],
        "選択肢1": ["選択肢Ａ","選択肢a","A","ａ"],
        "選択肢2": ["選択肢Ｂ","選択肢b","B","ｂ"],
        "選択肢3": ["選択肢Ｃ","選択肢c","C","ｃ"],
        "選択肢4": ["選択肢Ｄ","選択肢d","D","ｄ"],
        "選択肢5": ["選択肢Ｅ","選択肢e","E","ｅ"],
        "正解": ["解答","答え","ans","answer"],
        "科目分類": ["分類","科目","カテゴリ"],
        "リンクURL": ["画像URL","画像リンク","リンク"],
    }

    colset = set(df.columns)

    for canon, cands in alias.items():

        if canon in colset:
            continue

        for c in cands:

            if c in colset:

                df.rename(
                    columns={c: canon},
                    inplace=True
                )

                break

    return df

# =========================================================
# 安全取得
# =========================================================
def safe_get(row, keys, default=""):

    if isinstance(row, pd.Series):
        row = row.to_dict()

    for k in keys:

        if k in row:

            v = row.get(k)

            try:
                if pd.isna(v):
                    continue
            except Exception:
                pass

            s = str(v).strip()

            if s:
                return s

    return default

# =========================================================
# 必要列補完
# =========================================================
def ensure_output_columns(df):

    need = [
        "問題文",
        "選択肢1",
        "選択肢2",
        "選択肢3",
        "選択肢4",
        "選択肢5",
        "正解",
        "科目分類",
        "リンクURL"
    ]

    out = df.copy()

    for c in need:

        if c not in out.columns:
            out[c] = ""

    return out

# =========================================================
# DB読み込み
# =========================================================
df = pd.read_csv(
    "97_119DB.csv",
    dtype=str,
    encoding="utf-8-sig"
)

df = df.fillna("")

df = normalize_columns(df)

# =========================================================
# 行を全文テキスト化
# =========================================================
def row_text(r):

    parts = [
        safe_get(r, ["問題文","設問","問題","本文"]),
        *[
            safe_get(r, [f"選択肢{i}"])
            for i in range(1,6)
        ],
        safe_get(r, ["正解"]),
        safe_get(r, ["科目分類"]),
        safe_get(r, ["リンクURL"]),
    ]

    return " ".join(
        [p for p in parts if p]
    )

# =========================================================
# 問題番号抽出（コピペ）
# =========================================================
def extract_question_ids_from_text(text):

    ids = re.findall(
        r"\b\d{2,3}[A-Da-d]\d{1,3}-?\b",
        text
    )

    out = []
    seen = set()

    for qid in ids:

        qid = qid.upper().rstrip("-")

        if qid not in seen:

            out.append(qid)

            seen.add(qid)

    return out

# =========================================================
# txt/csvから問題番号抽出
# =========================================================
def extract_question_ids(uploaded_file):

    if uploaded_file is None:
        return []

    raw = uploaded_file.read()

    text = None

    for enc in (
        "utf-8-sig",
        "utf-8",
        "cp932",
        "shift_jis"
    ):

        try:

            text = raw.decode(enc)

            break

        except Exception:
            pass

    if text is None:

        text = raw.decode(
            "utf-8",
            errors="ignore"
        )

    return extract_question_ids_from_text(text)

# =========================================================
# 問題番号検索
# =========================================================
def filter_by_question_ids(df, qids):

    if not qids:

        return (
            pd.DataFrame(columns=df.columns),
            []
        )

    text_cache = df.apply(
        lambda row: row_text(row).upper(),
        axis=1
    )

    rows = []

    missing = []

    for qid in qids:

        pattern = (
            rf"(?<![0-9A-Z])"
            rf"{re.escape(qid)}"
            rf"(?:-|\b)"
        )

        hit_idx = text_cache[
            text_cache.str.contains(
                pattern,
                regex=True,
                na=False
            )
        ].index

        if len(hit_idx) == 0:

            missing.append(qid)

        else:

            rows.append(df.loc[hit_idx[0]])

    if not rows:

        return (
            pd.DataFrame(columns=df.columns),
            missing
        )

    return (
        pd.DataFrame(rows).reset_index(drop=True),
        missing
    )

# =========================================================
# GoogleDrive変換
# =========================================================
def convert_google_drive_link(url):

    if (
        "drive.google.com" in url
        and "/file/d/" in url
    ):

        try:

            file_id = (
                url
                .split("/file/d/")[1]
                .split("/")[0]
            )

            return (
                "https://drive.google.com/uc?export=view&id="
                + file_id
            )

        except Exception:

            return url

    return url

# =========================================================
# UI
# =========================================================

st.markdown("## 🔎 検索")

query = st.text_input(
    "問題文・選択肢・分類・URL検索"
)

st.caption(
    "💡 & でAND検索可能"
)

# =========================================================
# コピペ検索欄
# =========================================================
paste_text = st.text_area(
    "📋 問題番号をコピペ（99D82 など複数行OK）",
    height=180
)

search_paste_button = st.button(
    "🔍 問題番号検索"
)

# =========================================================
# ファイルアップロード
# =========================================================
list_file = st.file_uploader(
    "📂 問題番号リスト(txt/csv)をドラッグ＆ドロップ",
    type=["txt", "csv"]
)

# =========================================================
# 検索処理
# =========================================================

df_filtered = pd.DataFrame()

file_prefix = (
    datetime.now().strftime("%Y%m%d%H%M%S")
)

# ---------------------------------------------------------
# 1. コピペ検索
# ---------------------------------------------------------
if search_paste_button and paste_text.strip():

    st.session_state["pdf_bytes"] = None

    uploaded_qids = extract_question_ids_from_text(
        paste_text
    )

    df_filtered, missing_qids = filter_by_question_ids(
        df,
        uploaded_qids
    )

    st.success(
        f"{len(df_filtered)} 件ヒット"
    )

    if missing_qids:

        st.warning(
            "見つからなかった番号: "
            + ", ".join(missing_qids)
        )

    file_prefix = (
        "問題番号検索_"
        + file_prefix
    )

# ---------------------------------------------------------
# 2. ファイル検索
# ---------------------------------------------------------
elif list_file is not None:

    st.session_state["pdf_bytes"] = None

    uploaded_qids = extract_question_ids(
        list_file
    )

    df_filtered, missing_qids = filter_by_question_ids(
        df,
        uploaded_qids
    )

    st.success(
        f"{len(df_filtered)} 件ヒット"
    )

    if missing_qids:

        st.warning(
            "見つからなかった番号: "
            + ", ".join(missing_qids)
        )

    file_prefix = (
        "問題番号検索_"
        + file_prefix
    )

# ---------------------------------------------------------
# 3. 通常検索
# ---------------------------------------------------------
elif query.strip():

    st.session_state["pdf_bytes"] = None

    keywords = [
        kw.strip()
        for kw in query.split("&")
        if kw.strip()
    ]

    df_filtered = df[
        df.apply(
            lambda row:
            all(
                kw.lower()
                in row_text(row).lower()
                for kw in keywords
            ),
            axis=1
        )
    ]

    df_filtered = (
        df_filtered.reset_index(drop=True)
    )

    st.info(
        f"{len(df_filtered)} 件ヒット"
    )

    file_prefix = (
        query
        + "_"
        + file_prefix
    )

# ---------------------------------------------------------
# 入力なし
# ---------------------------------------------------------
else:

    st.stop()

# =========================================================
# CSVダウンロード
# =========================================================
csv_buffer = io.StringIO()

ensure_output_columns(df_filtered).to_csv(
    csv_buffer,
    index=False
)

st.download_button(
    label="📥 CSVダウンロード",
    data=csv_buffer.getvalue(),
    file_name=f"{file_prefix}.csv",
    mime="text/csv"
)

# =========================================================
# TEXTダウンロード
# =========================================================
def format_record_to_text(row):

    q = safe_get(
        row,
        ["問題文"]
    )

    parts = [f"問題文: {q}"]

    for i in range(1, 6):

        choice = safe_get(
            row,
            [f"選択肢{i}"]
        )

        if choice:

            parts.append(
                f"選択肢{i}: {choice}"
            )

    parts.append(
        f"正解: {safe_get(row,['正解'])}"
    )

    parts.append(
        f"分類: {safe_get(row,['科目分類'])}"
    )

    link = safe_get(
        row,
        ["リンクURL"]
    )

    if link:

        parts.append(
            "画像リンク: "
            + convert_google_drive_link(link)
        )

    return "\n".join(parts)

txt_buffer = io.StringIO()

for _, row in df_filtered.iterrows():

    txt_buffer.write(
        format_record_to_text(row)
    )

    txt_buffer.write(
        "\n\n"
        + "-" * 40
        + "\n\n"
    )

st.download_button(
    label="📄 TEXTダウンロード",
    data=txt_buffer.getvalue(),
    file_name=f"{file_prefix}.txt",
    mime="text/plain"
)

# =========================================================
# 一覧表示
# =========================================================
st.markdown("## 🔍 ヒットした問題一覧")

for i, (_, record) in enumerate(df_filtered.iterrows()):

    title = safe_get(
        record,
        ["問題文"]
    )

    with st.expander(
        f"{i+1}. {title[:50]}..."
    ):

        st.markdown("### 📝 問題文")

        st.write(title)

        st.markdown("### ✏️ 選択肢")

        for j in range(1, 6):

            val = safe_get(
                record,
                [f"選択肢{j}"]
            )

            if val:

                st.write(f"- {val}")

        show_ans = st.checkbox(
            "正解を表示",
            key=f"show_answer_{i}",
            value=False
        )

        if show_ans:

            st.markdown(
                f"**✅ 正解:** "
                f"{safe_get(record,['正解'])}"
            )

        else:

            st.markdown(
                "**✅ 正解:** "
                "|||（クリックで表示）|||"
            )

        st.markdown(
            f"**📚 分類:** "
            f"{safe_get(record,['科目分類'])}"
        )

        link = safe_get(
            record,
            ["リンクURL"]
        )

        if link:

            st.markdown(
                f"[画像リンクはこちら]"
                f"({convert_google_drive_link(link)})"
            )

        else:

            st.write("（画像リンクなし）")
