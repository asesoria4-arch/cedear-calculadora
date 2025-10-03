# ============================================================
# Antifragil Inversiones – Calculadora CEDEARs
# Autor: Diego + Asistente
# Última actualización: 2025-10-02
# ============================================================

import io
import re
import time
import hashlib
import requests
import pandas as pd
import yfinance as yf
import streamlit as st
from datetime import datetime
import pytz

# Backends de extracción de texto
from pdfminer.high_level import extract_text as pdfminer_extract_text
import fitz  # PyMuPDF

# --------------------------
# Configuración general
# --------------------------
st.set_page_config(page_title="Antifragil Inversiones – Calculadora CEDEARs", page_icon="💼", layout="centered")

# CSS (texto negro, tarjeta grande)
st.markdown("""
<style>
html, body, [class*="css"]  { color: #000 !important; }
label, .stTextInput label { font-size: 1.05rem !important; color: #000 !important; }
div[data-baseweb="input"] input { font-size: 1.05rem !important; }
.stButton>button { font-size: 1.05rem; padding: 0.6rem 1.1rem; }
.result-card {
  border: 2px solid #333; border-radius: 12px; padding: 16px 18px;
  background: #ffffff; font-size: 1.05rem; line-height: 1.6; color: #000000;
}
.result-card h3 { margin-top: 0; margin-bottom: 10px; color: #000; }
.result-highlight { font-size: 1.25rem; font-weight: 700; color: #000; }
.result-price { font-size: 1.25rem; font-weight: 700; color: #000; margin: 5px 0; }
</style>
""", unsafe_allow_html=True)

# --------------------------
# Título
# --------------------------
st.title("💼 Antifragil Inversiones – 💱 Calculadora CEDEARs")
st.caption("Ingresá un **ticker del subyacente** (ej: AAPL, MSFT, MELI, F). La app calcula el valor teórico del CEDEAR en USD y en ARS, usando **ratio BYMA** y **dólar CCL**.")

# --------------------------
# Fuentes de datos / Config
# --------------------------
DEFAULT_DRIVE_ID = "134hLt7AEujGcoPHhlywLS6ifUGxH-Jw7"
DEFAULT_DRIVE_URL = f"https://drive.google.com/uc?id={DEFAULT_DRIVE_ID}&export=download"
DOLAR_CCL_URL = "https://dolarapi.com/v1/dolares/contadoconliqui"

# --------------------------
# Utilidades
# --------------------------
STOPWORDS = {
    "CEDEAR","CEDEARS","BYMA","BOLSAS","MERCADOS","ARGENTINOS","RATIO",
    "VALOR","SUBYACENTE","ISIN","CUSIP","NASDAQ","NYSE","LSE","AMEX",
    "USD","ARS","ETF","SEDE","ACCION","EMPRESA","SECTOR","INDEX",
    "TABLE","PAGE","VOL","ADR","PROGRAMAS",
    "ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO","JULIO",
    "AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE"
}

def fmt(x, nd=2):
    try:
        return f"{float(x):,.{nd}f}"
    except Exception:
        return "0.00"

def fetch_bytes_from_url(url: str, timeout=25) -> bytes:
    r = requests.get(url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.content

# ------------ Extracción de texto ------------
def extract_text_pdfminer(pdf_bytes: bytes) -> str:
    try:
        return pdfminer_extract_text(io.BytesIO(pdf_bytes)) or ""
    except Exception:
        return ""

def extract_text_pymupdf(pdf_bytes: bytes) -> str:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        chunks = [page.get_text("text") for page in doc]
        doc.close()
        return "\n".join(chunks)
    except Exception:
        return ""

# ------------ Heurísticas de parseo de ratios ------------
TICKER_RE = re.compile(r"^[A-Z]{1,6}(?:\.[A-Z]{1,2})?$")
RATIO_RE = re.compile(r"^(\d{1,3}):1$")

def is_ticker_token(tok: str) -> bool:
    return bool(TICKER_RE.match(tok)) and tok not in STOPWORDS

def normalize_text(text: str) -> str:
    text = text.replace("\n", " ")
    return re.sub(r"\s+", " ", text)

def parse_ratios_from_text(text: str) -> dict:
    text = normalize_text(text)
    ratios = {}

    # 1) Match directo
    direct = re.findall(r"\b([A-Z0-9\.]{1,6})\b[^:]{0,60}?(\d{1,3}:1)", text)
    for tk, rx in direct:
        tk = re.sub(r"[^A-Z\.]", "", tk)
        if is_ticker_token(tk):
            ratios[tk] = int(rx.split(":")[0])

    # 2) Fallback si pocos
    if len(ratios) < 100:
        tokens = re.findall(r"[A-Z0-9\.]{1,10}|\d{1,3}:1", text)
        last_ticker = None
        for tok in tokens:
            if RATIO_RE.match(tok):
                if last_ticker and last_ticker not in ratios:
                    ratios[last_ticker] = int(tok.split(":")[0])
                    last_ticker = None
            else:
                t = re.sub(r"[^A-Z\.]", "", tok)
                if is_ticker_token(t):
                    last_ticker = t

    return ratios

def parse_ratios_from_pdf_bytes(pdf_bytes: bytes) -> dict:
    text1 = extract_text_pdfminer(pdf_bytes)
    ratios1 = parse_ratios_from_text(text1)
    if len(ratios1) >= 100:
        return ratios1
    text2 = extract_text_pymupdf(pdf_bytes)
    ratios2 = parse_ratios_from_text(text2)
    return ratios2 if len(ratios2) > len(ratios1) else ratios1

@st.cache_data(ttl=3600)
def load_ratios_from_source(mode: str, source: str = "") -> dict:
    if mode == "drive_default":
        pdf_bytes = fetch_bytes_from_url(DEFAULT_DRIVE_URL)
    elif mode == "url":
        pdf_bytes = fetch_bytes_from_url(source)
    elif mode == "upload":
        pdf_bytes = st.session_state["_upload_pdf_bytes"]
    else:
        return {}
    return parse_ratios_from_pdf_bytes(pdf_bytes)

@st.cache_data(ttl=300)
def get_ccl_price() -> float:
    try:
        data = requests.get(DOLAR_CCL_URL, timeout=10).json()
        return float(data["venta"])
    except Exception:
        return 0.0

def get_stock_price_usd(ticker: str) -> float:
    try:
        t = yf.Ticker(ticker)
        px = t.history(period="1d")["Close"].iloc[-1]
        return round(float(px), 2)
    except Exception:
        return 0.0

def calcular_precio_cedear(ticker: str, ratios: dict):
    if ticker not in ratios:
        return None, None, None, None, None
    price_usd = get_stock_price_usd(ticker)
    ratio = int(ratios.get(ticker, 0)) or 0
    ccl = get_ccl_price()
    if price_usd == 0 or ratio == 0 or ccl == 0:
        return price_usd, ratio, ccl, None, None
    precio_usd_cedear = round(price_usd / ratio, 2)
    precio_ars_cedear = round(precio_usd_cedear * ccl, 2)
    return price_usd, ratio, ccl, precio_usd_cedear, precio_ars_cedear

# --------------------------
# Sidebar
# --------------------------
st.sidebar.header("⚙️ Configuración de ratios CEDEAR")
mode = st.sidebar.radio(
    "Fuente del PDF de BYMA:",
    options=["Drive (por defecto)", "Pegar URL PDF", "Subir PDF"],
    index=0
)

ratios = {}
if mode == "Drive (por defecto)":
    try:
        ratios = load_ratios_from_source("drive_default")
    except Exception as e:
        st.sidebar.error(f"No pude cargar el PDF por defecto: {e}")

elif mode == "Pegar URL PDF":
    url_pdf = st.sidebar.text_input("URL directa a un PDF público", value=DEFAULT_DRIVE_URL)
    if url_pdf:
        try:
            ratios = load_ratios_from_source("url", url_pdf)
        except Exception as e:
            st.sidebar.error(f"No pude cargar el PDF de esa URL: {e}")

else:
    up = st.sidebar.file_uploader("Subí el PDF de BYMA", type=["pdf"])
    if up is not None:
        b = up.read()
        st.session_state["_upload_pdf_bytes"] = b
        key = hashlib.sha256(b).hexdigest()
        try:
            ratios = load_ratios_from_source("upload", key)
        except Exception as e:
            st.sidebar.error(f"No pude procesar el PDF subido: {e}")

if ratios:
    st.sidebar.success(f"Ratios cargados: {len(ratios)}")
    if len(ratios) < 100:
        st.sidebar.warning("⚠️ Se detectaron pocos tickers. El PDF podría tener un formato atípico.")
else:
    st.sidebar.warning("Aún no cargué ratios. Verificá la fuente elegida.")

# --------------------------
# App: Input y Cálculo
# --------------------------
col1, col2 = st.columns([2,1])
with col1:
    ticker = st.text_input("Ticker del subyacente (Ej: AAPL, MSFT, MELI, F):", value="AAPL").strip().upper()
with col2:
    go = st.button("Calcular CEDEAR", type="primary")

if "hist" not in st.session_state:
    st.session_state["hist"] = []

if go:
    if not ratios:
        st.error("No hay ratios cargados. Revisá la configuración en la barra lateral.")
    elif ticker not in ratios:
        st.error(f"El ticker **{ticker}** no figura en la tabla BYMA cargada.")
    else:
        with st.spinner("Calculando..."):
            px_usd, ratio, ccl, px_usd_cedear, px_ars_cedear = calcular_precio_cedear(ticker, ratios)

        if px_usd == 0 or ratio == 0 or ccl == 0 or px_usd_cedear is None:
            st.error("No se pudieron obtener todos los datos (precio USD, ratio o CCL).")
        else:
            st.markdown(f"""
<div class="result-card">
  <h3>📌 Cálculo CEDEAR para <b>{ticker}</b></h3>
  <p>💵 <b>Precio Acción:</b> {fmt(px_usd)} USD</p>
  <p>🔄 <b>Ratio CEDEAR:</b> {ratio}:1</p>
  <p>💲 <b>Dólar CCL:</b> {fmt(ccl)}</p>
  <hr>
  <p class="result-price">➡️ <b>Precio CEDEAR teórico USD:</b> {fmt(px_usd_cedear)} USD</p>
  <p class="result-price">➡️ <b>Precio CEDEAR teórico ARS:</b> ${fmt(px_ars_cedear)} ARS</p>
</div>
""", unsafe_allow_html=True)

            st.session_state["hist"].append({
                "Ticker": ticker,
                "Precio_USD": px_usd,
                "Ratio": ratio,
                "CCL": ccl,
                "Precio_CEDEAR_USD": px_usd_cedear,
                "Precio_CEDEAR_ARS": px_ars_cedear,
                "TS": datetime.now(pytz.timezone("America/Argentina/Buenos_Aires"))
            })

# --------------------------
# Historial + Exportar
# --------------------------
st.markdown("### 🗂️ Historial de cálculos (sesión)")
if len(st.session_state["hist"]) == 0:
    st.info("Todavía no hay cálculos en esta sesión.")
else:
    df = pd.DataFrame(st.session_state["hist"])

    if "TS" in df.columns:
        df["TS"] = pd.to_datetime(df["TS"]).dt.tz_localize(None)

    st.dataframe(df, use_container_width=True)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="CEDEARs")
    st.download_button(
        label="⬇️ Descargar Excel",
        data=buffer.getvalue(),
        file_name=f"cedears_{int(time.time())}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.markdown("---")
st.caption("Fuente ratios: BYMA (PDF). Precio USD: Yahoo Finance. CCL: dolarapi.com. Valores teóricos e informativos.")
