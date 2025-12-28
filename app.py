# =====================================================
# MÓDULO 1 — BASE FUNCIONAL GLOBAL (SUPABASE / POSTGRES)
# =====================================================

# ========================
# IMPORTS
# ========================
import streamlit as st
import pandas as pd
import os
import json
import base64
import psycopg2
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from streamlit_cookies_manager import EncryptedCookieManager

st.session_state.setdefault("bloquear_cookie", False)

# ========================
# COOKIES + SESSÃO (ÚNICO PONTO)
# ========================
cookies = EncryptedCookieManager(
    prefix="petiko_app",
    password="COLOQUE_UMA_SENHA_FORTE_AQUI"
)

if not cookies.ready():
    st.stop()

if "logado" not in st.session_state:
    if (
        cookies.get("logado") == "true"
        and not st.session_state.get("bloquear_cookie", False)
    ):
        st.session_state["logado"] = True
        st.session_state["usuario"] = cookies.get("usuario")
        st.session_state["perfil"] = cookies.get("perfil")
    else:
        st.session_state["logado"] = False
        st.session_state["usuario"] = None
        st.session_state["perfil"] = None

# ========================
# CONFIG STREAMLIT
# ========================
st.set_page_config(layout="wide")

# ========================
# SUPABASE — CONFIGURAÇÃO
# 🔁 MIGRAÇÃO SQLITE → POSTGRES
# ========================
def get_conn():
    cfg = st.secrets["database"]
    return psycopg2.connect(
        host=cfg["host"],
        dbname=cfg["dbname"],
        user=cfg["user"],
        password=cfg["password"],
        port=cfg["port"],
        sslmode="require"
    )

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            sku TEXT PRIMARY KEY,
            descricao TEXT,
            quantidade INTEGER,
            localizacao TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pedidos (
            pedido TEXT PRIMARY KEY,
            data TEXT,
            status TEXT,
            dados_fin TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS itens_pedido (
            id SERIAL PRIMARY KEY,
            pedido TEXT,
            sku TEXT,
            descricao TEXT,
            quantidade INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id SERIAL PRIMARY KEY,
            data TEXT,
            sku TEXT,
            descricao TEXT,
            tipo TEXT,
            quantidade INTEGER,
            pedido TEXT,
            obs TEXT
        )
    """)

    # 🔹 HISTÓRICO COM RESPONSÁVEL
    cur.execute("""
        CREATE TABLE IF NOT EXISTS historico_pedidos (
            id SERIAL PRIMARY KEY,
            pedido TEXT,
            data TEXT,
            acao TEXT,
            detalhe TEXT,
            responsavel TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

# ========================
# FUNÇÕES — LEITURA (POSTGRES)
# ========================
def ler_tabela(nome):
    conn = get_conn()
    df = pd.read_sql(f"SELECT * FROM {nome}", conn)
    conn.close()
    return df

# ========================
# FUNÇÕES — SALVAR
# (simula to_sql replace do SQLite)
# ========================
def salvar_tabela(nome, df):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(f"DELETE FROM {nome}")

    if not df.empty:
        cols = list(df.columns)
        placeholders = ", ".join(["%s"] * len(cols))
        colnames = ", ".join(cols)

        for _, row in df.iterrows():
            cur.execute(
                f"INSERT INTO {nome} ({colnames}) VALUES ({placeholders})",
                tuple(row.values)
            )

    conn.commit()
    conn.close()

# ========================
# LOAD GLOBAL (OBRIGATÓRIO)
# ========================
produtos = ler_tabela("produtos")
pedidos  = ler_tabela("pedidos")
itens    = ler_tabela("itens_pedido")
movs     = ler_tabela("movimentacoes")
hist     = ler_tabela("historico_pedidos")

# ========================
# GARANTE COLUNAS (ANTI-ERRO)
# ========================
def garantir_colunas(df, colunas):
    for c in colunas:
        if c not in df.columns:
            df[c] = ""
    return df

produtos = garantir_colunas(
    produtos,
    ["sku", "descricao", "quantidade", "localizacao"]
)

pedidos = garantir_colunas(
    pedidos,
    ["pedido", "data", "status", "dados_fin"]
)

itens = garantir_colunas(
    itens,
    ["pedido", "sku", "descricao", "quantidade"]
)

movs = garantir_colunas(
    movs,
    ["data", "sku", "descricao", "tipo", "quantidade", "pedido", "obs"]
)

hist = garantir_colunas(
    hist,
    ["pedido", "data", "acao", "detalhe", "responsavel"]
)

# ========================
# SAVE GLOBAL (ÚNICO)
# ========================
def save_all():
    salvar_tabela("produtos", produtos)
    salvar_tabela("pedidos", pedidos)
    salvar_tabela("itens_pedido", itens)
    salvar_tabela("movimentacoes", movs)
    salvar_tabela("historico_pedidos", hist)

# ========================
# LEITURA SEGURA dados_fin
# ========================
def ler_dados_fin(pedido):
    raw = pedidos.loc[
        pedidos["pedido"] == pedido,
        "dados_fin"
    ].values

    if raw.size == 0 or pd.isna(raw[0]) or str(raw[0]).strip() == "":
        return {}

    try:
        return json.loads(str(raw[0]))
    except:
        return {}

# ========================
# HISTÓRICO DE PEDIDOS
# ========================
def registrar_historico(pedido, acao, detalhe):
    global hist

    usuario = st.session_state.get("usuario", "sistema")

    novo = pd.DataFrame([{
        "pedido": pedido,
        "data": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "acao": acao,
        "detalhe": detalhe,
        "responsavel": usuario
    }])

    hist = pd.concat([hist, novo], ignore_index=True)
    salvar_tabela("historico_pedidos", hist)

def ultimo_comentario_analista(pedido):
    f = hist[
        (hist["pedido"] == pedido) &
        (hist["acao"] == "DEVOLVIDO PARA INNOVA")
    ]

    if f.empty:
        return None

    return f.iloc[-1]["detalhe"]

# ========================
# MOVIMENTAÇÃO DE ESTOQUE
# ========================
def registrar_mov(sku, desc, tipo, qtd, pedido="", obs=""):
    global movs

    novo = pd.DataFrame([{
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "sku": sku,
        "descricao": desc,
        "tipo": tipo,
        "quantidade": int(qtd),
        "pedido": pedido,
        "obs": obs
    }])

    movs = pd.concat([movs, novo], ignore_index=True)
    salvar_tabela("movimentacoes", movs)

# ========================
# STATUS COLORS (GLOBAL)
# ========================
status_color = {
    "ABERTO": "#546e7a",
    "SEPARACAO": "#1e88e5",
    "MONTAGEM": "#1976d2",
    "OCORRENCIA": "#e53935",
    "ANALISAR": "#fb8c00",
    "ENTRADA": "#9e9e9e",
    "SAIDA": "#7b1fa2",
    "FINALIZADO": "#43a047",
    "AJUSTE": "#e91e63"
}

# ========================
# SESSION STATE BASE
# ========================
st.session_state.setdefault("modo", None)
st.session_state.setdefault("menu", None)
# =====================================================
# MÓDULO 2 — UI GLOBAL (CSS + HEADER + LOGOS)
# =====================================================

# ========================
# FUNÇÃO PARA IMAGEM BASE64
# ========================
def img_to_base64(path):
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# ========================
# LOGOS
# ========================
LOGO_INNOVA    = img_to_base64("logo_innova.png")
LOGO_PETIKO    = img_to_base64("logo_petiko.png")
LOGO_WATERMARK = img_to_base64("logo_watermark.png")

# =================================================
# CSS GLOBAL (VERSÃO FINAL — SIDEBAR COM RODAPÉ FIXO)
# =================================================
st.markdown("""
<style>

/* ================= HEADER ================= */
.app-header {
    position: sticky;
    top: 0;
    z-index: 999;
    background: #ffffff;
    padding: 10px 24px;
    border-bottom: 1px solid #eaeaea;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.app-header img {
    height: 42px;
}

.app-title {
    text-align: center;
    font-size: 20px;
    font-weight: 800;
    color: #263238;
    letter-spacing: 0.5px;
}

/* ================= MARCA D’ÁGUA ================= */
.watermark {
    position: fixed;
    bottom: 18px;
    right: 18px;
    opacity: 0.06;
    z-index: 0;
}

.watermark img {
    width: 220px;
}

/* garante conteúdo acima da marca */
section.main > div {
    position: relative;
    z-index: 2;
}

/* ================= SIDEBAR ================= */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0b1c2d, #102a43);
}

/* container REAL da sidebar */
div[data-testid="stSidebarContent"] {
    position: relative;
    min-height: 100vh;
    padding-bottom: 64px;
}

section[data-testid="stSidebar"] * {
    color: #ffffff !important;
    font-weight: 600;
}

section[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.15);
}

/* ================= RODAPÉ FIXO ================= */
.sidebar-fixed-footer {
    position: absolute;
    bottom: 0;
    left: 0;
    width: 100%;
    padding: 10px 14px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-top: 1px solid rgba(255,255,255,0.15);
    background: linear-gradient(180deg, #0b1c2d, #102a43);
}

.sidebar-fixed-user {
    display: flex;
    flex-direction: column;
    font-size: 13px;
    line-height: 1.1;
    font-weight: 700;
}

.sidebar-fixed-user small {
    font-size: 11px;
    opacity: 0.85;
}

/* ================= BOTÕES SIDEBAR — SEM FLASH ================= */
section[data-testid="stSidebar"] button {
    background: #0b1c2d !important;
    color: #ffffff !important;
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
}

section[data-testid="stSidebar"] button:hover {
    background: #102a43 !important;
    color: #ffffff !important;
}

section[data-testid="stSidebar"] button:active {
    background: #0b1c2d !important;
    color: #ffffff !important;
}

section[data-testid="stSidebar"] button:focus {
    background: #0b1c2d !important;
    color: #ffffff !important;
    box-shadow: none !important;
    outline: none !important;
}

section[data-testid="stSidebar"] button div {
    background: transparent !important;
}

/* ================= PADRÕES ================= */
.badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 22px;
    height: 22px;
    padding: 0 7px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    color: #fff;
    margin-left: 6px;
}

.header { font-size:14px; font-weight:600; }
.cell   { font-size:15px; }
.sku    { font-size:17px; font-weight:800; }
.box    { padding:6px; border-bottom:1px solid #eee; }

/* ================= REMOVE OLHO DO CAMPO PASSWORD ================= */
input[type="password"]::-ms-reveal,
input[type="password"]::-ms-clear {
    display: none;
}

input[type="password"]::-webkit-credentials-auto-fill-button,
input[type="password"]::-webkit-textfield-decoration-container {
    display: none !important;
}

/* ================= INPUTS DA SIDEBAR ================= */
section[data-testid="stSidebar"] input {
    background: #0b1c2d !important;
    color: #ffffff !important;
    border: 1px solid rgba(255,255,255,0.25) !important;
    box-shadow: none !important;
}

section[data-testid="stSidebar"] input::placeholder {
    color: rgba(255,255,255,0.6) !important;
}

section[data-testid="stSidebar"] input:focus {
    background: #0b1c2d !important;
    color: #ffffff !important;
    border: 1px solid #ffffff !important;
    box-shadow: none !important;
    outline: none !important;
}

section[data-testid="stSidebar"] div[data-baseweb="input"] {
    background: #0b1c2d !important;
    border-radius: 8px;
}

section[data-testid="stSidebar"] div[data-baseweb="input"]:hover {
    background: #102a43 !important;
}

section[data-testid="stSidebar"] div[data-baseweb="input"] svg {
    fill: #ffffff !important;
    background: transparent !important;
}

</style>
""", unsafe_allow_html=True)

# =================================================
# HEADER + MARCA D’ÁGUA
# =================================================
st.markdown(
    f"""
    <div class="app-header">
        <img src="data:image/png;base64,{LOGO_INNOVA}">
        <div class="app-title">
            POUCHS E EMBALAGENS<br>
            <span style="font-size:13px;font-weight:600;">
                PETIKO - INNOVA
            </span>
        </div>
        <img src="data:image/png;base64,{LOGO_PETIKO}">
    </div>

    <div class="watermark">
        <img src="data:image/png;base64,{LOGO_WATERMARK}">
    </div>
    """,
    unsafe_allow_html=True
)

# =====================================================
# ======================== USUÁRIOS ===================
# =====================================================

import hashlib
import psycopg2

# =====================================================
# CRIA TABELA DE USUÁRIOS (POSTGRES)
# =====================================================
def criar_tabela_usuarios():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            usuario TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL,
            perfil TEXT NOT NULL,
            ativo INTEGER DEFAULT 1,
            criado_em TEXT
        )
    """)

    conn.commit()
    conn.close()

# =====================================================
# HASH DE SENHA
# =====================================================
def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

# =====================================================
# CRIAR USUÁRIO
# =====================================================
def criar_usuario(usuario, senha, perfil):
    conn = get_conn()
    c = conn.cursor()

    try:
        c.execute("""
            INSERT INTO usuarios (usuario, senha, perfil, ativo, criado_em)
            VALUES (%s, %s, %s, 1, %s)
        """, (
            usuario,
            hash_senha(senha),
            perfil,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()
        sucesso = True
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        sucesso = False

    conn.close()
    return sucesso

# =====================================================
# VALIDAR LOGIN
# =====================================================
def validar_login(usuario, senha):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        SELECT usuario, perfil
        FROM usuarios
        WHERE usuario = %s
          AND senha = %s
          AND ativo = 1
    """, (
        usuario,
        hash_senha(senha)
    ))

    row = c.fetchone()
    conn.close()

    if row:
        return {"usuario": row[0], "perfil": row[1]}
    return None

# =====================================================
# ALTERAR SENHA DO PRÓPRIO USUÁRIO
# =====================================================
def alterar_senha(usuario, nova_senha):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE usuarios
        SET senha = %s
        WHERE usuario = %s
          AND ativo = 1
    """, (
        hash_senha(nova_senha),
        usuario
    ))

    conn.commit()
    conn.close()

# =====================================================
# GARANTE TABELA E CRIA USUÁRIO TESTE
# =====================================================
criar_tabela_usuarios()
criar_usuario("humberto", "1234", "ANALISTA")

# =====================================================
# ======================== LOGIN ======================
# =====================================================

def logout():
    st.session_state["logado"] = False
    st.session_state["usuario"] = None
    st.session_state["perfil"] = None
    st.rerun()

def tela_login():
    st.markdown("<br><br>", unsafe_allow_html=True)

    col_esq, col_centro, col_dir = st.columns([1, 1.2, 1])

    with col_centro:
        st.markdown("""
        <div style="
            background:#ffffff;
            padding:22px;
            border-radius:10px;
            box-shadow:0 8px 20px rgba(0,0,0,0.15);
            ">
            <div style="text-align:center;font-size:18px;font-weight:800;">
                Acesso ao Sistema
            </div>
            <div style="text-align:center;font-size:12px;color:#607d8b;margin-bottom:14px;">
                PETIKO · INNOVA
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            usuario = st.text_input("Usuário")
            senha = st.text_input("Senha", type="password")
            entrar = st.form_submit_button("Entrar", use_container_width=True)

        if entrar:
            dados = validar_login(usuario, senha)

            if dados:
                st.session_state["logado"] = True
                st.session_state["usuario"] = dados["usuario"]
                st.session_state["perfil"] = dados["perfil"]

                cookies["logado"] = "true"
                cookies["usuario"] = dados["usuario"]
                cookies["perfil"] = dados["perfil"]
                cookies.save()

                st.rerun()
            else:
                st.error("Usuário ou senha inválidos")

if not st.session_state["logado"]:
    tela_login()
    st.stop()

# =====================================================
# CONTROLE DE ACESSO POR PERFIL
# =====================================================
PERMISSOES = {
    "ANALISTA": [
        "📦 Produtos","🧾 Pedidos","📋 Estoque","🏭 Innova",
        "🕵️ Analista","🗂️ Gerenciador","📍 Acompanhar Fluxo","👤 Usuários"
    ],
    "PRODUTO": ["📦 Produtos","🧾 Pedidos","📍 Acompanhar Fluxo"],
    "ESTOQUE": ["📦 Produtos","📋 Estoque","📍 Acompanhar Fluxo"],
    "INNOVA": ["🏭 Innova","📍 Acompanhar Fluxo"]
}

with st.sidebar:
    st.markdown(
        f"""
        <div class="sidebar-footer">
            <div class="sidebar-user">
                {st.session_state["usuario"]}
                <small>{st.session_state["perfil"]}</small>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
