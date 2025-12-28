# ========================
# IMPORTS
# ========================
import streamlit as st
import pandas as pd
import os
import json
import base64
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from streamlit_cookies_manager import EncryptedCookieManager
import psycopg2

# ========================
# CONFIG STREAMLIT
# ========================
st.set_page_config(layout="wide")

# ========================
# CONEXÃO POSTGRES (SUPABASE)
# 🔁 MIGRAÇÃO POSTGRES — substitui SQLite
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

# ========================
# TESTE DE CONEXÃO (INALTERADO NA LÓGICA)
# ========================
try:
    conn = get_conn()
    conn.close()
except Exception as e:
    st.error(f"Erro de conexão com banco: {e}")
    st.stop()

# ========================
# COOKIES + SESSÃO (ÚNICO PONTO)
# ========================
st.session_state.setdefault("bloquear_cookie", False)

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
# INIT DB — POSTGRES
# 🔁 MIGRAÇÃO POSTGRES
# ========================
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
# FUNÇÕES — LEITURA
# 🔁 MIGRAÇÃO POSTGRES
# ========================
def ler_tabela(nome):
    conn = get_conn()
    df = pd.read_sql(f"SELECT * FROM {nome}", conn)
    conn.close()
    return df

# ========================
# FUNÇÕES — SALVAR (SIMULA SQLite)
# 🔁 MIGRAÇÃO POSTGRES
# ========================
def salvar_tabela(nome, df):
    conn = get_conn()
    cur = conn.cursor()

    # apaga tudo (equivalente ao replace do SQLite)
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

/* botão de mostrar senha */
input[type="password"]::-ms-reveal,
input[type="password"]::-ms-clear {
    display: none;
}

/* Chrome / Edge / Safari */
input[type="password"]::-webkit-credentials-auto-fill-button,
input[type="password"]::-webkit-textfield-decoration-container {
    display: none !important;
}
/* ================= INPUTS DA SIDEBAR — AZUL ESCURO ================= */

/* container do input */
section[data-testid="stSidebar"] input {
    background: #0b1c2d !important;
    color: #ffffff !important;
    border: 1px solid rgba(255,255,255,0.25) !important;
    box-shadow: none !important;
}

/* placeholder */
section[data-testid="stSidebar"] input::placeholder {
    color: rgba(255,255,255,0.6) !important;
}

/* foco */
section[data-testid="stSidebar"] input:focus {
    background: #0b1c2d !important;
    color: #ffffff !important;
    border: 1px solid #ffffff !important;
    box-shadow: none !important;
    outline: none !important;
}

/* remove qualquer fundo branco interno */
section[data-testid="stSidebar"] input div,
section[data-testid="stSidebar"] input span {
    background: transparent !important;
}

/* wrapper do input (Streamlit) */
section[data-testid="stSidebar"] div[data-baseweb="input"] {
    background: #0b1c2d !important;
    border-radius: 8px;
}

/* hover */
section[data-testid="stSidebar"] div[data-baseweb="input"]:hover {
    background: #102a43 !important;
}

/* ícone (olho) — mantém invisível e sem fundo */
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

# =====================================================
# CRIA TABELA DE USUÁRIOS (POSTGRES)
# 🔁 MIGRAÇÃO POSTGRES — ajuste AUTOINCREMENT → SERIAL
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
            VALUES (?, ?, ?, 1, ?)
        """, (
            usuario,
            hash_senha(senha),
            perfil,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        conn.commit()
        sucesso = True

    except sqlite3.IntegrityError:
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
        WHERE usuario = ?
          AND senha = ?
          AND ativo = 1
    """, (
        usuario,
        hash_senha(senha)
    ))

    row = c.fetchone()
    conn.close()

    if row:
        return {
            "usuario": row[0],
            "perfil": row[1]
        }

    return None
# =====================================================
# ALTERAR SENHA DO PRÓPRIO USUÁRIO
# =====================================================
def alterar_senha(usuario, nova_senha):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE usuarios
        SET senha = ?
        WHERE usuario = ?
          AND ativo = 1
    """, (
        hash_senha(nova_senha),
        usuario
    ))

    conn.commit()
    conn.close()


# =====================================================
# GARANTE TABELA E CRIA USUÁRIO TESTE (RODAR UMA VEZ)
# =====================================================
criar_tabela_usuarios()
criar_usuario("humberto", "1234", "ANALISTA")


# =====================================================
# ======================== LOGIN ======================
# =====================================================

# -------- LOGOUT --------
def logout():
    st.session_state["logado"] = False
    st.session_state["usuario"] = None
    st.session_state["perfil"] = None
    st.rerun()


# -------- TELA DE LOGIN --------
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

                # 🔐 SALVA COOKIE AQUI (SÓ AQUI)
                cookies["logado"] = "true"
                cookies["usuario"] = dados["usuario"]
                cookies["perfil"] = dados["perfil"]
                cookies.save()

                st.rerun()
            else:
                st.error("Usuário ou senha inválidos")


# -------- BLOQUEIO GLOBAL --------
if not st.session_state["logado"]:
    tela_login()
    st.stop()
# =====================================================
# CONTROLE DE ACESSO POR PERFIL
# =====================================================
PERMISSOES = {
    "ANALISTA": [
        "📦 Produtos",
        "🧾 Pedidos",
        "📋 Estoque",
        "🏭 Innova",
        "🕵️ Analista",
        "🗂️ Gerenciador",
        "📍 Acompanhar Fluxo",
        "👤 Usuários"
    ],
    "PRODUTO": [
        "📦 Produtos",
        "🧾 Pedidos",
        "📍 Acompanhar Fluxo"
    ],
    "ESTOQUE": [
        "📦 Produtos",
        "📋 Estoque",
        "📍 Acompanhar Fluxo"
    ],
    "INNOVA": [
        "🏭 Innova",
        "📍 Acompanhar Fluxo"
    ]
}
# -------- RODAPÉ FIXO DA SIDEBAR (APENAS INFORMAÇÕES DO USUÁRIO) --------
with st.sidebar:

    st.markdown("""
    <style>
    /* container real da sidebar */
    div[data-testid="stSidebarContent"] {
        position: relative;
        min-height: 100vh;
        padding-bottom: 60px;
    }

    .sidebar-footer {
        position: absolute;
        bottom: 0;
        left: 0;
        width: 100%;
        padding: 12px 14px;
        display: flex;
        align-items: center;
        background: linear-gradient(180deg, #0b1c2d, #102a43);
        border-top: 1px solid rgba(255,255,255,0.15);
        z-index: 999;
    }

    .sidebar-user {
        display: flex;
        flex-direction: column;
        font-size: 13px;
        line-height: 1.2;
        font-weight: 700;
    }

    .sidebar-user small {
        font-size: 11px;
        opacity: 0.85;
        font-weight: 600;
    }
    </style>
    """, unsafe_allow_html=True)

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
# =====================================================
# MÓDULO 3 — MENU PRINCIPAL
# =====================================================

# menu padrão (segurança)
if "menu" not in st.session_state:
    st.session_state["menu"] = "📦 Produtos"
# =====================================================
# 🔑 ALTERAR SENHA — APENAS USUÁRIO LOGADO
# =====================================================
if st.session_state.get("logado"):

    with st.sidebar:

        with st.expander("🔑 Alterar senha", expanded=False):

            nova = st.text_input(
                "Nova senha",
                type="password",
                key="nova_senha"
            )

            confirmar = st.text_input(
                "Confirmar nova senha",
                type="password",
                key="conf_senha"
            )

            if st.button("Salvar nova senha"):
                if not nova or not confirmar:
                    st.error("Informe a nova senha.")
                elif nova != confirmar:
                    st.error("As senhas não conferem.")
                elif len(nova) < 4:
                    st.error("A senha deve ter pelo menos 4 caracteres.")
                else:
                    alterar_senha(
                        st.session_state["usuario"],
                        nova
                    )
                    st.success("Senha alterada com sucesso.")
# =====================================================
# PERMISSÕES POR PERFIL
# =====================================================
PERMISSOES_MENU = {
    "ANALISTA": [
        "📦 Produtos",
        "🧾 Pedidos",
        "📋 Estoque",
        "🏭 Innova",
        "🕵️ Analista",
        "🗂️ Gerenciador",
        "📍 Acompanhar Fluxo",
        "👤 Usuários"
    ],
    "PRODUTO": [
        "📦 Produtos",
        "🧾 Pedidos",
        "📍 Acompanhar Fluxo"
    ],
    "ESTOQUE": [
        "📦 Produtos",
        "📋 Estoque",
        "📍 Acompanhar Fluxo"
    ],
    "INNOVA": [
        "🏭 Innova",
        "📍 Acompanhar Fluxo"
    ]
}

with st.sidebar:

    # ============================
    # 🔐 CONTROLE DE SESSÃO
    # ============================
    if "logado" not in st.session_state or not st.session_state.get("logado"):
        st.warning("Sessão expirada. Faça login novamente.")
        st.stop()

    perfil = st.session_state.get("perfil")

    # ============================
    # 🛡️ PERMISSÕES DE MENU
    # ============================
    menu_opcoes = PERMISSOES_MENU.get(perfil, [])

    if not menu_opcoes:
        st.error("Perfil sem permissões configuradas.")
        st.stop()

    # ============================
    # 📋 MENU
    # ============================
    escolha = st.radio(
        "Menu",
        menu_opcoes,
        key="menu_radio"
    )

    # sincroniza com session_state
    st.session_state["menu"] = escolha

    # ============================
    # 🚪 LOGOUT (PORTA DE SAÍDA)
    # ============================
    st.divider()

    if st.button("🚪 Logout", use_container_width=True):

        # 🔒 bloqueia relogin automático
        st.session_state["bloquear_cookie"] = True

        # remove cookie explicitamente
        cookies["logado"] = ""
        cookies["usuario"] = ""
        cookies["perfil"] = ""
        cookies.save()

        # limpa sessão
        st.session_state["logado"] = False
        st.session_state["usuario"] = None
        st.session_state["perfil"] = None

        st.rerun()
# =====================================================
# VARIÁVEL GLOBAL USADA PELO SISTEMA
# =====================================================
menu = st.session_state["menu"]
# =====================================================
# MÓDULO 4 — 📦 PRODUTOS
# =====================================================

if menu == "📦 Produtos":
    st.title("📦 PRODUTOS")

    # =================================================
    # NORMALIZAÇÃO DE SCHEMA (ANTI-ERRO)
    # =================================================
    for col in ["sku", "descricao", "categoria", "quantidade", "localizacao"]:
        if col not in produtos.columns:
            if col == "categoria":
                produtos[col] = "Embalagem"
            elif col == "quantidade":
                produtos[col] = 0
            else:
                produtos[col] = ""

    produtos["quantidade"] = (
        pd.to_numeric(produtos["quantidade"], errors="coerce")
        .fillna(0)
        .astype(int)
    )

    produtos["categoria"] = produtos["categoria"].where(
        produtos["categoria"].isin(["Embalagem", "Pouch"]),
        "Embalagem"
    )

    produtos = produtos[
        ["sku", "descricao", "categoria", "quantidade", "localizacao"]
    ]

    save_all()

    # =================================================
    # ➕ CADASTRAR NOVO PRODUTO
    # =================================================
    with st.expander("➕ CADASTRAR NOVO PRODUTO"):
        with st.form("novo_produto"):
            sku = st.text_input("SKU")
            desc = st.text_input("DESCRIÇÃO")
            categoria = st.selectbox("CATEGORIA", ["Embalagem", "Pouch"])
            qtd = st.number_input("QUANTIDADE INICIAL", min_value=0, step=1)
            loc = st.text_input("LOCALIZAÇÃO")

            if st.form_submit_button("SALVAR"):
                if not sku:
                    st.error("Informe o SKU.")
                elif sku in produtos["sku"].astype(str).values:
                    st.error("SKU já existe.")
                else:
                    produtos.loc[len(produtos)] = {
                        "sku": sku,
                        "descricao": desc,
                        "categoria": categoria,
                        "quantidade": int(qtd),
                        "localizacao": loc
                    }

                    registrar_mov(
                        sku, desc, "ENTRADA", qtd, obs="Cadastro inicial"
                    )

                    save_all()
                    st.success("Produto cadastrado com sucesso.")
                    st.rerun()

    # =================================================
    # 🔎 BUSCA
    # =================================================
    busca = st.text_input("🔍 Buscar por SKU ou descrição").lower().strip()

    produtos_vis = produtos.copy()
    if busca:
        produtos_vis = produtos_vis[
            produtos_vis["sku"].str.lower().str.contains(busca)
            | produtos_vis["descricao"].str.lower().str.contains(busca)
        ]

    # =================================================
    # 🎨 ESTILOS DOS CARDS
    # =================================================
    st.markdown("""
<style>
.card {
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 8px;
}
.embalagem {
    background: #fff7ed;
    border-left: 6px solid #ff9800;
}
.pouch {
    background: #eef7f1;
    border-left: 6px solid #4caf50;
}
.card-top {
    margin-bottom: 14px;
}
.card-sku {
    font-size: 16px;
    font-weight: 800;
    margin-bottom: 4px;
}
.card-desc {
    font-size: 14px;
    color: #444;
}
.card-info {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
}
.card-label {
    font-size: 12px;
    color: #777;
}
.card-value {
    font-size: 15px;
    font-weight: 700;
}
.manage-box {
    border: 1px solid #e0e0e0;
    border-radius: 10px;
    padding: 12px;
    background: #fafafa;
    margin-bottom: 14px;
}
</style>
""", unsafe_allow_html=True)

    # =================================================
    # 📦 LISTAGEM EM CARDS
    # =================================================
    for _, prod in produtos_vis.iterrows():
        sku = prod["sku"]
        classe = "embalagem" if prod["categoria"] == "Embalagem" else "pouch"

        st.markdown(
f"""
<div class="card {classe}">
<div class="card-top">
<div class="card-sku">SKU: {sku}</div>
<div class="card-desc">DESCRIÇÃO: {prod['descricao']}</div>
</div>

<div class="card-info">
<div>
<div class="card-label">ESTOQUE</div>
<div class="card-value">{prod['quantidade']}</div>
</div>
<div>
<div class="card-label">CATEGORIA</div>
<div class="card-value">{prod['categoria']}</div>
</div>
<div>
<div class="card-label">LOCALIZAÇÃO</div>
<div class="card-value">{prod['localizacao']}</div>
</div>
</div>
</div>
""",
unsafe_allow_html=True
        )

        col_spacer, col_btn = st.columns([8, 2])
        with col_btn:
            if st.button("⚙️ Gerenciar", key=f"ger_{sku}"):
                st.session_state["produto_ativo"] = sku
                st.session_state.pop("acao_produto", None)

        # =================================================
        # 🧠 GERENCIAMENTO INLINE
        # =================================================
        if st.session_state.get("produto_ativo") == sku:
            p = produtos[produtos["sku"] == sku].iloc[0]
            idx = produtos[produtos["sku"] == sku].index[0]

            col_t, col_x = st.columns([9, 1])
            col_t.markdown(f"#### ⚙️ {p['sku']} — {p['descricao']}")
            if col_x.button("❌", key=f"close_{sku}"):
                st.session_state.pop("produto_ativo", None)
                st.session_state.pop("acao_produto", None)
                st.rerun()

            st.markdown("<div class='manage-box'>", unsafe_allow_html=True)

            b1, b2, b3, b4, b5 = st.columns(5)
            if b1.button("➕ Entrada", key=f"ent_btn_{sku}"):
                st.session_state["acao_produto"] = "ENTRADA"
            if b2.button("➖ Saída", key=f"sai_btn_{sku}"):
                st.session_state["acao_produto"] = "SAIDA"
            if b3.button("✏️ Editar", key=f"edit_btn_{sku}"):
                st.session_state["acao_produto"] = "EDITAR"
            if b4.button("📜 Histórico", key=f"hist_btn_{sku}"):
                st.session_state["acao_produto"] = "HIST"
            if b5.button("🗑️ Excluir", key=f"del_btn_{sku}"):
                st.session_state["acao_produto"] = "DEL"

            st.divider()
            acao = st.session_state.get("acao_produto")

            if acao == "ENTRADA":
                valor = st.number_input("Quantidade", min_value=1, step=1, key=f"ent_{sku}")
                obs = st.text_input("Obs", key=f"obs_ent_{sku}")
                if st.button("Confirmar", key=f"conf_ent_{sku}"):
                    produtos.loc[idx, "quantidade"] += int(valor)
                    registrar_mov(p["sku"], p["descricao"], "ENTRADA", valor, obs=obs)
                    save_all()
                    st.session_state.pop("produto_ativo", None)
                    st.session_state.pop("acao_produto", None)
                    st.rerun()

            if acao == "SAIDA":
                valor = st.number_input("Quantidade", min_value=1, step=1, key=f"sai_{sku}")
                obs = st.text_input("Obs", key=f"obs_sai_{sku}")
                if st.button("Confirmar", key=f"conf_sai_{sku}"):
                    if produtos.loc[idx, "quantidade"] >= valor:
                        produtos.loc[idx, "quantidade"] -= int(valor)
                        registrar_mov(p["sku"], p["descricao"], "SAIDA", valor, obs=obs)
                        save_all()
                        st.session_state.pop("produto_ativo", None)
                        st.session_state.pop("acao_produto", None)
                        st.rerun()
                    else:
                        st.error("Quantidade insuficiente.")

            if acao == "EDITAR":
                desc_novo = st.text_input("Descrição", p["descricao"], key=f"d_{sku}")
                loc_novo = st.text_input("Localização", p["localizacao"], key=f"l_{sku}")
                if st.button("Salvar alterações", key=f"save_{sku}"):
                    produtos.loc[idx, "descricao"] = desc_novo
                    produtos.loc[idx, "localizacao"] = loc_novo
                    save_all()
                    st.session_state.pop("produto_ativo", None)
                    st.session_state.pop("acao_produto", None)
                    st.rerun()

            if acao == "HIST":
                hist_p = movs[movs["sku"] == sku]
                st.dataframe(hist_p, hide_index=True, use_container_width=True)

            if acao == "DEL":
                st.warning("Essa ação não pode ser desfeita.")
                if st.button("Confirmar exclusão", key=f"del_conf_{sku}"):
                    produtos.drop(idx, inplace=True)
                    produtos.reset_index(drop=True, inplace=True)
                    save_all()
                    st.session_state.pop("produto_ativo", None)
                    st.session_state.pop("acao_produto", None)
                    st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)
# =====================================================
# MÓDULO 5 — 🧾 PEDIDOS
# =====================================================

if menu == "🧾 Pedidos":
    st.subheader("🧾 Pedidos")

    # =================================================
    # BOTÕES DE AÇÃO
    # =================================================
    colA, colB = st.columns([1, 1])

    if colA.button("➕ Novo Pedido"):
        st.session_state["modo"] = "novo"

    if colB.button("🔍 Buscar Pedido"):
        st.session_state["modo"] = "buscar"

    modo = st.session_state.get("modo")

    # =================================================
    # NOVO PEDIDO
    # =================================================
    if modo == "novo":
        with st.form("novo_pedido"):
            nome = st.text_input("Nome do Pedido")

            if st.form_submit_button("Criar") and nome:
                pedidos.loc[len(pedidos)] = {
                    "pedido": nome,
                    "data": datetime.now().strftime("%d/%m/%Y"),
                    "status": "ABERTO",
                    "dados_fin": ""
                }

                save_all()
                st.session_state["pedido_aberto"] = nome
                st.session_state["modo"] = "editar"
                st.rerun()

    # =================================================
    # BUSCAR PEDIDO
    # =================================================
    if modo == "buscar":
        busca = st.text_input("Buscar pedido por nome")

        lista = pedidos[pedidos["status"] == "ABERTO"].copy()

        if busca:
            lista = lista[
                lista["pedido"]
                .astype(str)
                .str.contains(busca, case=False, na=False)
            ]

        for idx, p in lista.iterrows():
            if st.button(
                f"{p['pedido']} — {p['status']}",
                key=f"open_{p['pedido']}_{idx}"
            ):
                st.session_state["pedido_aberto"] = p["pedido"]
                st.session_state["modo"] = "editar"
                st.rerun()

    # =================================================
    # EDITAR PEDIDO
    # =================================================
    if st.session_state.get("modo") == "editar":
        pedido = st.session_state["pedido_aberto"]

        linha_status = pedidos.loc[
            pedidos["pedido"] == pedido,
            "status"
        ]

        if linha_status.empty:
            st.session_state.pop("pedido_aberto", None)
            st.session_state.pop("modo", None)
            st.rerun()

        status = linha_status.values[0]

        st.markdown(f"### Pedido: **{pedido}**")
        st.markdown(f"**Status:** {status}")

        # =================================================
        # BUSCAR PRODUTO
        # =================================================
        busca_prod = st.text_input("Buscar produto")

        if busca_prod:
            lista_prod = produtos[
                produtos["sku"].astype(str).str.contains(busca_prod, case=False, na=False) |
                produtos["descricao"].astype(str).str.contains(busca_prod, case=False, na=False)
            ]
        else:
            lista_prod = pd.DataFrame()

        for _, p in lista_prod.iterrows():
            c1, c2 = st.columns([5, 1])

            estoque_atual = int(p.get("quantidade", 0))

            c1.markdown(
                f"""
                **{p['sku']} — {p['descricao']}**  
                <span style="color:#6c757d; font-size:13px;">
                Estoque disponível: {estoque_atual}
                </span>
                """,
                unsafe_allow_html=True
            )

            if c2.button("➕", key=f"add_{pedido}_{p['sku']}"):
                itens.loc[len(itens)] = {
                    "pedido": pedido,
                    "sku": p["sku"],
                    "descricao": p["descricao"],
                    "quantidade": 1
                }
                save_all()
                st.rerun()
        # =================================================
        # ITENS DO PEDIDO
        # =================================================
        itens_p = itens[itens["pedido"] == pedido]

        for _, it in itens_p.iterrows():
            c1, c2, c3 = st.columns([5, 2, 1])

            c1.write(it["descricao"])

            nova_qtd = c2.number_input(
                "Qtd",
                value=int(it["quantidade"]),
                min_value=1,
                key=f"pedido_qtd_{pedido}_{it['sku']}_{it.name}"
            )

            if nova_qtd != it["quantidade"]:
                itens.loc[
                    (itens["pedido"] == pedido) &
                    (itens["sku"] == it["sku"]),
                    "quantidade"
                ] = int(nova_qtd)

                save_all()
                st.rerun()

            if c3.button("🗑️", key=f"d_{pedido}_{it['sku']}"):
                itens.drop(
                    itens[
                        (itens["pedido"] == pedido) &
                        (itens["sku"] == it["sku"])
                    ].index,
                    inplace=True
                )
                save_all()
                st.rerun()

        st.divider()

        # =================================================
        # AÇÕES DO PEDIDO
        # =================================================
        col1, col2, col3 = st.columns(3)

        if col1.button("✅ Finalizar Pedido"):
            pedidos.loc[
                pedidos["pedido"] == pedido,
                "status"
            ] = "SEPARACAO"

            save_all()
            st.session_state.pop("pedido_aberto")
            st.session_state.pop("modo")
            st.rerun()

        if col2.button("❌ Cancelar Pedido"):
            itens.drop(
                itens[itens["pedido"] == pedido].index,
                inplace=True
            )
            pedidos.drop(
                pedidos[pedidos["pedido"] == pedido].index,
                inplace=True
            )
            save_all()
            st.session_state.pop("pedido_aberto")
            st.session_state.pop("modo")
            st.rerun()

        if col3.button("🔙 Fechar"):
            st.session_state.pop("pedido_aberto")
            st.session_state.pop("modo")
            st.rerun()
# =====================================================
# 📄 PDF DE ESTOQUE — RELATÓRIO DE SEPARAÇÃO (INTEGRAL)
# =====================================================

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from datetime import datetime


def gerar_pdf_estoque(pedido):
    """
    Gera o PDF de separação de estoque para um pedido.
    Retorna o nome do arquivo gerado.
    """

    nome = f"RELATORIO_ESTOQUE_{pedido}_{datetime.now().strftime('%d-%m-%Y')}.pdf"
    c = canvas.Canvas(nome, pagesize=A4)
    w, h = A4

    # =================================================
    # TÍTULO
    # =================================================
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(
        w / 2,
        h - 40,
        "RELATÓRIO DE SEPARAÇÃO – ESTOQUE"
    )

    # =================================================
    # CABEÇALHO
    # =================================================
    c.setFont("Helvetica", 11)
    c.drawString(40, h - 70, f"Pedido: {pedido}")
    c.drawRightString(
        w - 40,
        h - 70,
        f"Data: {datetime.now().strftime('%d/%m/%Y')}"
    )

    # =================================================
    # CABEÇALHO DA TABELA
    # =================================================
    y = h - 120

    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "SKU")
    c.drawString(140, y, "Descrição")
    c.drawRightString(w - 40, y, "Quantidade")

    y -= 6
    c.line(40, y, w - 40, y)
    y -= 18

    # =================================================
    # ITENS DO PEDIDO
    # =================================================
    c.setFont("Helvetica", 10)

    itens_p = itens[itens["pedido"] == pedido]

    if itens_p.empty:
        c.drawString(40, y, "Nenhum item encontrado para este pedido.")
        y -= 16
    else:
        for _, it in itens_p.iterrows():
            c.drawString(40, y, str(it["sku"]))
            c.drawString(140, y, str(it["descricao"]))
            c.drawRightString(
                w - 40,
                y,
                str(int(it["quantidade"]))
            )
            y -= 16

            # -----------------------------
            # QUEBRA DE PÁGINA AUTOMÁTICA
            # -----------------------------
            if y < 120:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = h - 80

                # Reimprime cabeçalho da tabela
                c.setFont("Helvetica-Bold", 11)
                c.drawString(40, y, "SKU")
                c.drawString(140, y, "Descrição")
                c.drawRightString(w - 40, y, "Quantidade")
                y -= 6
                c.line(40, y, w - 40, y)
                y -= 18
                c.setFont("Helvetica", 10)

    # =================================================
    # ASSINATURAS
    # =================================================
    c.line(40, 90, 260, 90)
    c.setFont("Helvetica", 10)
    c.drawString(40, 75, "Assinatura INNOVA")

    c.line(320, 90, w - 40, 90)
    c.drawString(320, 75, "Assinatura PETIKO")

    # =================================================
    # FINALIZA
    # =================================================
    c.save()
    return nome
# =====================================================
# MÓDULO 6 — 📋 ESTOQUE
# =====================================================

if menu == "📋 Estoque":
    st.subheader("📋 Estoque — Pedidos em Separação")

    # =================================================
    # LISTA DE PEDIDOS EM SEPARAÇÃO
    # =================================================
    lista = pedidos[pedidos["status"] == "SEPARACAO"]

    if lista.empty:
        st.info("Nenhum pedido em separação")

    for _, p in lista.iterrows():
        pedido = p["pedido"]

        with st.expander(f"🧾 {pedido}"):

            itens_p = itens[itens["pedido"] == pedido]

            # =================================================
            # ITENS DO PEDIDO (EDITÁVEL)
            # =================================================
            if itens_p.empty:
                st.info("Pedido sem itens.")
            else:
                for _, it in itens_p.iterrows():
                    c1, c2, c3 = st.columns([5, 2, 1])

                    c1.write(f"{it['sku']} — {it['descricao']}")

                    nova_qtd = c2.number_input(
                        "Qtd",
                        value=int(it["quantidade"]),
                        min_value=1,
                        key=f"estoque_qtd_{pedido}_{it['sku']}_{it.name}"
                    )

                    if nova_qtd != it["quantidade"]:
                        itens.loc[
                            (itens["pedido"] == pedido) &
                            (itens["sku"] == it["sku"]),
                            "quantidade"
                        ] = int(nova_qtd)

                        save_all()
                        st.rerun()

                    if c3.button("🗑️", key=f"del_est_{pedido}_{it['sku']}"):
                        itens.drop(
                            itens[
                                (itens["pedido"] == pedido) &
                                (itens["sku"] == it["sku"])
                            ].index,
                            inplace=True
                        )
                        save_all()
                        st.rerun()

            st.divider()

            # =================================================
            # AÇÕES DO PEDIDO
            # =================================================
            col1, col2, col3 = st.columns(3)

            # ---------------- PDF DE ESTOQUE ----------------
            if col1.button("📄 Gerar Relatório", key=f"pdf_{pedido}"):
                arq = gerar_pdf_estoque(p["pedido"])
                with open(arq, "rb") as f:
                    st.download_button(
                        "⬇️ Baixar PDF",
                        data=f,
                        file_name=arq,
                        mime="application/pdf"
                    )

            # ---------------- CANCELAR PEDIDO ----------------
            if col2.button("❌ Cancelar Pedido", key=f"cancelar_{pedido}"):
                pedidos.loc[
                    pedidos["pedido"] == pedido,
                    "status"
                ] = "CANCELADO"

                save_all()
                st.success("Pedido cancelado.")
                st.rerun()

            # ---------------- FINALIZAR ESTOQUE ----------------
            if col3.button("✅ Finalizar Estoque", key=f"fin_{pedido}"):

                for _, it in itens_p.iterrows():
                    idx = produtos[
                        produtos["sku"] == it["sku"]
                    ].index[0]

                    produtos.loc[idx, "quantidade"] -= int(it["quantidade"])

                    registrar_mov(
                        it["sku"],
                        it["descricao"],
                        "SAIDA_PEDIDO",
                        it["quantidade"],
                        pedido
                    )

                pedidos.loc[
                    pedidos["pedido"] == pedido,
                    "status"
                ] = "MONTAGEM"

                save_all()
                st.success(
                    "Estoque abatido e pedido enviado para Montagem."
                )
                st.rerun()
# =====================================================
# ======================== PDF INNOVA =================
# =====================================================

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from datetime import datetime


# -----------------------------------------------------
# LIMPA SKU E DESCRIÇÃO DO ITEM ACABADO
# -----------------------------------------------------
def limpar_item_acabado(sku, desc):
    if sku.endswith("P"):
        sku = sku[:-1]

    if desc.upper().startswith("POUCH"):
        desc = desc.replace("POUCH", "", 1).strip()

    return sku, desc


# -----------------------------------------------------
# DESENHA TABELA PADRÃO NO PDF
# -----------------------------------------------------
def desenhar_tabela(c, x, y, titulo, linhas):
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, titulo)
    y -= 18

    # Cabeçalho
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x, y, "SKU")
    c.drawString(x + 120, y, "Descrição")
    c.drawRightString(x + 480, y, "Qtd")
    y -= 6

    c.line(x, y, x + 480, y)
    y -= 14

    c.setFont("Helvetica", 10)

    if linhas:
        for l in linhas:
            c.drawString(x, y, str(l["sku"]))
            c.drawString(x + 120, y, str(l["desc"]))
            c.drawRightString(x + 480, y, str(l["qtd"]))
            y -= 16
    else:
        c.drawString(x, y, "—")
        y -= 16

    return y - 10


# -----------------------------------------------------
# GERA ROMANEIO PDF — INNOVA (MODELO VALIDADO)
# -----------------------------------------------------
def gerar_romaneio(pedido, dados):
    nome = f"ROMANEIO_{pedido}_{datetime.now().strftime('%d-%m-%Y')}.pdf"
    c = canvas.Canvas(nome, pagesize=A4)
    w, h = A4

    # ========================
    # TÍTULO
    # ========================
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(
        w / 2,
        h - 40,
        "ROMANEIO EMBALAGEM / POUCH"
    )

    # ========================
    # CABEÇALHO
    # ========================
    c.setFont("Helvetica", 11)
    c.drawString(40, h - 70, f"Pedido: {pedido}")
    c.drawRightString(
        w - 40,
        h - 70,
        f"Data: {datetime.now().strftime('%d/%m/%Y')}"
    )

    y = h - 120

    # ========================
    # ITEM ACABADO
    # ========================
    sku, desc = limpar_item_acabado(
        dados["final"]["sku"],
        dados["final"]["desc"]
    )

    y = desenhar_tabela(
        c,
        40,
        y,
        "ITEM ACABADO",
        [{
            "sku": sku,
            "desc": desc,
            "qtd": dados["final"]["qtd"]
        }]
    )

    # ========================
    # SOBRA
    # ========================
    y = desenhar_tabela(
        c,
        40,
        y,
        "SOBRA",
        dados.get("sobra", [])
    )

    # ========================
    # FALTA
    # ========================
    y = desenhar_tabela(
        c,
        40,
        y,
        "FALTA",
        dados.get("falta", [])
    )

    # ========================
    # AVARIA
    # ========================
    y = desenhar_tabela(
        c,
        40,
        y,
        "AVARIA",
        dados.get("avaria", [])
    )

    # ========================
    # ASSINATURAS
    # ========================
    c.line(40, 80, 260, 80)
    c.setFont("Helvetica", 10)
    c.drawString(40, 65, "Assinatura INNOVA")

    c.line(320, 80, w - 40, 80)
    c.drawString(320, 65, "Assinatura PETIKO")

    c.save()
    return nome

# =====================================================
# MÓDULO 7 — 🏭 INNOVA
# =====================================================

if menu == "🏭 Innova":
    st.title("🏭 INNOVA")

    # ========================
    # SESSION STATE
    # ========================
    st.session_state.setdefault("ocorrencias_ativas", {})
    st.session_state.setdefault("oc_aberta", {})
    st.session_state.setdefault("fin_on", {})
    st.session_state.setdefault("etapa", {})
    st.session_state.setdefault("dados_fin", {})

    # ========================
    # PEDIDOS VISÍVEIS
    # ========================
    pedidos_validos = pedidos[pedidos["status"].isin(["MONTAGEM", "OCORRENCIA"])]

    if pedidos_validos.empty:
        st.info("Nenhum pedido em montagem ou ocorrência.")

    for _, p in pedidos_validos.iterrows():
        pedido = p["pedido"]
        status_pedido = p["status"]
        itens_pedido = itens[itens["pedido"] == pedido].to_dict("records")

        st.session_state["ocorrencias_ativas"].setdefault(pedido, [])
        st.session_state["oc_aberta"].setdefault(pedido, False)
        st.session_state["fin_on"].setdefault(pedido, False)
        st.session_state["etapa"].setdefault(pedido, 0)
        st.session_state["dados_fin"].setdefault(
            pedido,
            {"final": {}, "sobra": [], "falta": [], "avaria": []}
        )

        with st.expander(f"🧾 {pedido} — {status_pedido}"):

            coment = ultimo_comentario_analista(pedido)
            if coment:
                st.info(f"📝 Comentário do Analista: {coment}")

            st.subheader("📦 Itens do Pedido")
            st.dataframe(
                pd.DataFrame([
                    {
                        "SKU": it["sku"],
                        "Descrição": it["descricao"],
                        "Quantidade": int(it["quantidade"])
                    } for it in itens_pedido
                ]),
                hide_index=True,
                use_container_width=True
            )

            st.divider()

            if status_pedido == "OCORRENCIA":
                st.warning("⏳ Pedido em análise. Aguarde.")
                continue

            # ========================
            # 🚨 OCORRÊNCIAS
            # ========================
            st.subheader("🚨 Ocorrências")

            if st.button("🚨 ABRIR OCORRÊNCIA", key=f"abrir_oc_{pedido}"):
                st.session_state["oc_aberta"][pedido] = True

            if st.session_state["oc_aberta"][pedido]:
                tipo = st.selectbox(
                    "Tipo",
                    ["FALTA DE ITEM", "MATERIAL INCORRETO", "AVARIA"],
                    key=f"tipo_oc_{pedido}"
                )

                item = st.selectbox(
                    "Item",
                    [i["descricao"] for i in itens_pedido],
                    key=f"item_oc_{pedido}"
                )

                qtd = st.number_input(
                    "Quantidade",
                    min_value=1,
                    step=1,
                    key=f"qtd_oc_{pedido}"
                )

                if st.button("➕ INCLUIR", key=f"add_oc_{pedido}"):
                    prod = next(i for i in itens_pedido if i["descricao"] == item)

                    st.session_state["ocorrencias_ativas"][pedido].append({
                        "tipo": tipo,
                        "sku": prod["sku"],
                        "desc": prod["descricao"],
                        "qtd": int(qtd)
                    })

                    st.session_state["oc_aberta"][pedido] = False
                    st.rerun()

            if st.session_state["ocorrencias_ativas"][pedido]:
                for oc in st.session_state["ocorrencias_ativas"][pedido]:
                    st.write(f"{oc['tipo']} — {oc['desc']} ({oc['qtd']})")

                if st.button("📨 ENVIAR PARA ANÁLISE", key=f"send_{pedido}"):
                    dados = st.session_state["dados_fin"][pedido]
                    dados["ocorrencias"] = st.session_state["ocorrencias_ativas"][pedido]

                    pedidos.loc[pedidos["pedido"] == pedido, "dados_fin"] = json.dumps(dados)
                    pedidos.loc[pedidos["pedido"] == pedido, "status"] = "OCORRENCIA"

                    st.session_state["ocorrencias_ativas"][pedido] = []
                    save_all()
                    st.rerun()

            st.divider()

            # ========================
            # FINALIZAÇÃO
            # ========================
            if not st.session_state["fin_on"][pedido]:
                if st.button("✅ INICIAR FINALIZAÇÃO", key=f"ini_{pedido}"):
                    st.session_state["fin_on"][pedido] = True
                    st.session_state["etapa"][pedido] = 0
                    st.rerun()

            if st.session_state["fin_on"][pedido]:
                etapa = st.session_state["etapa"][pedido]
                dados = st.session_state["dados_fin"][pedido]

                if etapa == 0:
                    st.subheader("📦 Item Acabado")

                    prod = st.selectbox(
                        "Produto final",
                        [i["descricao"] for i in itens_pedido],
                        key=f"fin_prod_{pedido}"
                    )

                    qtd = st.number_input(
                        "Quantidade produzida",
                        min_value=0,
                        step=1,
                        key=f"fin_qtd_{pedido}"
                    )

                    if st.button("➡️ Próximo", key=f"n0_{pedido}"):
                        psel = next(i for i in itens_pedido if i["descricao"] == prod)
                        dados["final"] = {
                            "sku": psel["sku"],
                            "desc": psel["descricao"],
                            "qtd": int(qtd)
                        }
                        st.session_state["etapa"][pedido] = 1
                        st.rerun()

                def etapa_lista(titulo, chave, atual, prox):
                    st.subheader(titulo)

                    prod = st.selectbox(
                        "Item",
                        ["-- selecionar --"] + [i["descricao"] for i in itens_pedido],
                        key=f"{chave}_prod_{pedido}"
                    )

                    if prod != "-- selecionar --":
                        qtd = st.number_input(
                            "Quantidade",
                            min_value=1,
                            step=1,
                            key=f"{chave}_qtd_{pedido}"
                        )

                        if st.button("➕ Adicionar", key=f"add_{chave}_{pedido}"):
                            psel = next(i for i in itens_pedido if i["descricao"] == prod)
                            dados[chave].append({
                                "sku": psel["sku"],
                                "desc": psel["descricao"],
                                "qtd": int(qtd)
                            })
                            st.rerun()

                    for x in dados[chave]:
                        st.write(f"- {x['desc']} ({x['qtd']})")

                    c1, c2 = st.columns(2)

                    if c1.button("⬅️ Voltar", key=f"b_{chave}_{pedido}"):
                        st.session_state["etapa"][pedido] = atual - 1
                        st.rerun()

                    if c2.button("➡️ Próximo", key=f"n_{chave}_{pedido}"):
                        st.session_state["etapa"][pedido] = prox
                        st.rerun()

                if etapa == 1:
                    etapa_lista("➕ SOBRA", "sobra", 1, 2)

                if etapa == 2:
                    etapa_lista("➖ FALTA", "falta", 2, 3)

                if etapa == 3:
                    etapa_lista("⚠️ AVARIA", "avaria", 3, 4)

                if etapa == 4:
                    st.subheader("✅ Finalizar")

                    if st.button("✅ GERAR ROMANEIO (PDF)", key=f"pdf_{pedido}"):

                        pedidos.loc[
                            pedidos["pedido"] == pedido,
                            "dados_fin"
                        ] = json.dumps(dados)

                        save_all()

                        pdf = gerar_romaneio(pedido, dados)

                        tem_sobra  = len(dados["sobra"])  > 0
                        tem_falta  = len(dados["falta"])  > 0
                        tem_avaria = len(dados["avaria"]) > 0

                        total = sum([tem_sobra, tem_falta, tem_avaria])

                        if total > 1:
                            novo_status = "ANALISAR"
                        elif tem_sobra:
                            novo_status = "ENTRADA"
                        elif tem_falta or tem_avaria:
                            novo_status = "SAIDA"
                        else:
                            novo_status = "FINALIZADO"

                        pedidos.loc[pedidos["pedido"] == pedido, "status"] = novo_status
                        save_all()

                        with open(pdf, "rb") as f:
                            st.download_button(
                                "⬇️ Finalizar",
                                data=f,
                                file_name=pdf,
                                mime="application/pdf",
                                key=f"down_{pedido}"
                            )
# =====================================================
# ======================== ANALISTA ===================
# =====================================================
if menu == "🕵️ Analista":
    st.title("🕵️ ANALISTA")

    # ========================
    # NORMALIZA STATUS
    # ========================
    pedidos["status"] = (
        pedidos["status"]
        .astype(str)
        .str.upper()
        .str.strip()
        .str.replace("EM ", "")
        .str.replace("Ç", "C")
        .str.replace("Ã", "A")
    )

    # ========================
    # FILTROS POR STATUS
    # ========================
    pedidos_oc  = pedidos[pedidos["status"] == "OCORRENCIA"]
    pedidos_ent = pedidos[pedidos["status"] == "ENTRADA"]
    pedidos_sai = pedidos[pedidos["status"] == "SAIDA"]
    pedidos_ana = pedidos[pedidos["status"] == "ANALISAR"]

    pedidos_aj = pedidos[
        pedidos["status"]
        .astype(str)
        .str.contains("AJUSTE", na=False)
    ]

    # ========================
    # TABS (OBRIGATÓRIO ANTES DO USO)
    # ========================
    tab_oc, tab_ent, tab_sai, tab_ana, tab_aj = st.tabs([
        f"🚨 Ocorrência ({len(pedidos_oc)})",
        f"⬆️ Entrada ({len(pedidos_ent)})",
        f"⬇️ Saída ({len(pedidos_sai)})",
        f"🧠 Analisar ({len(pedidos_ana)})",
        f"🛠️ Ajuste ({len(pedidos_aj)})"
    ])

    # =================================================
    # 🚨 OCORRÊNCIA
    # =================================================
    with tab_oc:
        if pedidos_oc.empty:
            st.info("Nenhum pedido em ocorrência.")
        else:
            for _, p in pedidos_oc.iterrows():
                pedido = p["pedido"]
                dados = ler_dados_fin(pedido)
                ocorrencias = dados.get("ocorrencias", [])

                with st.expander(f"🧾 {pedido}"):

                    # ---- OCORRÊNCIAS ----
                    if ocorrencias:
                        df_oc = pd.DataFrame([
                            {
                                "Tipo": oc.get("tipo", ""),
                                "SKU": oc.get("sku", ""),
                                "Descrição": oc.get("desc", ""),
                                "Quantidade": oc.get("qtd", 0)
                            }
                            for oc in ocorrencias
                        ])
                        st.dataframe(df_oc, hide_index=True, use_container_width=True)
                    else:
                        st.info("Nenhuma ocorrência registrada.")

                    st.divider()

                    # ---- TRATATIVA ----
                    comentario = st.text_area(
                        "Comentário do Analista",
                        key=f"oc_com_{pedido}"
                    )

                    prazo = st.date_input(
                        "Prazo para correção",
                        key=f"oc_pr_{pedido}"
                    )

                    if st.button("↩ DEVOLVER PARA INNOVA", key=f"ret_{pedido}"):
                        if not comentario:
                            st.error("Informe o comentário.")
                            st.stop()

                        registrar_historico(
                            pedido,
                            "DEVOLVIDO PARA INNOVA",
                            f"{comentario} | Prazo {prazo.strftime('%d/%m/%Y')}"
                        )

                        pedidos.loc[
                            pedidos["pedido"] == pedido,
                            "status"
                        ] = "MONTAGEM"

                        save_all()
                        st.success("Pedido devolvido para a Innova.")
                        st.rerun()

                    st.divider()

                    # ---- HISTÓRICO ----
                    hist_p = hist[hist["pedido"] == pedido]

                    if not hist_p.empty:
                        hist_p = hist_p.sort_values("data", ascending=False)

                        st.markdown("### 📜 Histórico do Pedido")

                        st.dataframe(
                            hist_p[[
                                "data",
                                "acao",
                                "detalhe",
                                "responsavel"
                            ]].rename(columns={
                                "data": "Data",
                                "acao": "Ação",
                                "detalhe": "Detalhe",
                                "responsavel": "Responsável"
                            }),
                            hide_index=True,
                            use_container_width=True
                        )
    # =================================================
    # ⬆️ ENTRADA (SOBRA)
    # =================================================
    with tab_ent:
        if pedidos_ent.empty:
            st.info("Nenhum pedido em entrada.")
        else:
            for _, p in pedidos_ent.iterrows():
                pedido = p["pedido"]
                dados = ler_dados_fin(pedido)
                sobras = dados.get("sobra", [])

                if not sobras:
                    continue

                with st.expander(f"🧾 {pedido}"):
                    linhas = []
                    for it in sobras:
                        qtd_ini = itens.loc[
                            (itens["pedido"] == pedido) &
                            (itens["sku"] == it["sku"]),
                            "quantidade"
                        ].sum()

                        linhas.append({
                            "SKU": it["sku"],
                            "Produto": it["desc"],
                            "Qtd Inicial": int(qtd_ini) if pd.notna(qtd_ini) else 0,
                            "Qtd Final": int(it["qtd"])
                        })

                    df = pd.DataFrame(linhas)

                    edit = st.data_editor(
                        df,
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "Qtd Inicial": st.column_config.NumberColumn(disabled=True),
                            "Qtd Final": st.column_config.NumberColumn(min_value=0)
                        },
                        key=f"ent_{pedido}"
                    )

                    if st.button("📦 LANÇAR ENTRADA EM ESTOQUE", key=f"ent_lan_{pedido}"):
                        for _, r in edit.iterrows():
                            qtd = int(r["Qtd Final"])

                            produtos.loc[
                                produtos["sku"] == r["SKU"],
                                "quantidade"
                            ] += qtd

                            registrar_mov(
                                r["SKU"],
                                r["Produto"],
                                "ENTRADA",
                                qtd,
                                pedido
                            )

                        registrar_historico(
                            pedido,
                            "ENTRADA DE ESTOQUE",
                            "Sobras lançadas no estoque"
                        )

                        pedidos.loc[
                            pedidos["pedido"] == pedido,
                            "status"
                        ] = "FINALIZADO"

                        save_all()
                        st.success("Entrada lançada e pedido finalizado.")
                        st.rerun()
    # =================================================
    # ⬇️ SAÍDA (FALTA / AVARIA)
    # =================================================
    with tab_sai:
        if pedidos_sai.empty:
            st.info("Nenhum pedido em saída.")
        else:
            for _, p in pedidos_sai.iterrows():
                pedido = p["pedido"]
                dados = ler_dados_fin(pedido)

                linhas = []
                for origem in ["falta", "avaria"]:
                    for it in dados.get(origem, []):
                        qtd_ini = itens.loc[
                            (itens["pedido"] == pedido) &
                            (itens["sku"] == it["sku"]),
                            "quantidade"
                        ].sum()

                        linhas.append({
                            "SKU": it["sku"],
                            "Produto": it["desc"],
                            "Tipo": origem.upper(),
                            "Qtd Inicial": int(qtd_ini) if pd.notna(qtd_ini) else 0,
                            "Qtd Final": int(it["qtd"])
                        })

                if not linhas:
                    continue

                with st.expander(f"🧾 {pedido}"):
                    df = pd.DataFrame(linhas)

                    edit = st.data_editor(
                        df,
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "Qtd Inicial": st.column_config.NumberColumn(disabled=True),
                            "Qtd Final": st.column_config.NumberColumn(min_value=0)
                        },
                        key=f"sai_{pedido}"
                    )

                    if st.button("📦 LANÇAR SAÍDA EM ESTOQUE", key=f"sai_lan_{pedido}"):
                        for _, r in edit.iterrows():
                            qtd = int(r["Qtd Final"])

                            produtos.loc[
                                produtos["sku"] == r["SKU"],
                                "quantidade"
                            ] -= qtd

                            registrar_mov(
                                r["SKU"],
                                r["Produto"],
                                "SAIDA",
                                qtd,
                                pedido
                            )

                        registrar_historico(
                            pedido,
                            "SAÍDA DE ESTOQUE",
                            "Faltas / avarias lançadas"
                        )

                        pedidos.loc[
                            pedidos["pedido"] == pedido,
                            "status"
                        ] = "FINALIZADO"

                        save_all()
                        st.success("Saída lançada e pedido finalizado.")
                        st.rerun()
    # =================================================
    # 🧠 ANALISAR (DECISÃO MISTA)
    # =================================================
    with tab_ana:
        if pedidos_ana.empty:
            st.info("Nenhum pedido para análise.")
        else:
            for _, p in pedidos_ana.iterrows():
                pedido = p["pedido"]
                dados = ler_dados_fin(pedido)

                linhas = []
                for origem, mov in [
                    ("sobra", "ENTRADA"),
                    ("falta", "SAIDA"),
                    ("avaria", "SAIDA")
                ]:
                    for it in dados.get(origem, []):
                        qtd_ini = itens.loc[
                            (itens["pedido"] == pedido) &
                            (itens["sku"] == it["sku"]),
                            "quantidade"
                        ].sum()

                        linhas.append({
                            "SKU": it["sku"],
                            "Produto": it["desc"],
                            "Origem": origem.upper(),
                            "Qtd Inicial": int(qtd_ini) if pd.notna(qtd_ini) else 0,
                            "Qtd Final": int(it["qtd"]),
                            "Movimento": mov
                        })

                if not linhas:
                    continue

                with st.expander(f"🧾 {pedido}"):
                    df = pd.DataFrame(linhas)

                    edit = st.data_editor(
                        df,
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "Qtd Inicial": st.column_config.NumberColumn(disabled=True),
                            "Qtd Final": st.column_config.NumberColumn(min_value=0),
                            "Movimento": st.column_config.SelectboxColumn(
                                options=["ENTRADA", "SAIDA"]
                            )
                        },
                        key=f"ana_{pedido}"
                    )

                    if st.button("📦 CONFIRMAR LANÇAMENTO", key=f"ana_lan_{pedido}"):
                        for _, r in edit.iterrows():
                            qtd = int(r["Qtd Final"])

                            if r["Movimento"] == "ENTRADA":
                                produtos.loc[
                                    produtos["sku"] == r["SKU"],
                                    "quantidade"
                                ] += qtd
                            else:
                                produtos.loc[
                                    produtos["sku"] == r["SKU"],
                                    "quantidade"
                                ] -= qtd

                            registrar_mov(
                                r["SKU"],
                                r["Produto"],
                                r["Movimento"],
                                qtd,
                                pedido
                            )

                        registrar_historico(
                            pedido,
                            "ANÁLISE FINAL",
                            "Estoque ajustado após análise"
                        )

                        pedidos.loc[
                            pedidos["pedido"] == pedido,
                            "status"
                        ] = "FINALIZADO"

                        save_all()
                        st.success("Análise concluída e pedido finalizado.")
                        st.rerun()
    # =================================================
    # 🛠️ AJUSTE DE PEDIDO (EDIÇÃO TOTAL)
    # =================================================
    with tab_aj:
        if pedidos_aj.empty:
            st.info("Nenhum pedido em ajuste.")
        else:
            for _, p in pedidos_aj.iterrows():
                pedido = p["pedido"]
                dados = ler_dados_fin(pedido)

                comentario = dados.get("comentario_ajuste", "")
                status_origem = dados.get("status_origem", "ABERTO")

                with st.expander(f"🧾 {pedido}"):

                    st.warning("⚠️ MODO AJUSTE — edição total liberada")
                    st.info(f"📝 Solicitação: {comentario}")

                    # =================================================
                    # ✏️ EDITAR NOME DO PEDIDO
                    # =================================================
                    novo_nome = st.text_input(
                        "Nome do Pedido",
                        value=pedido,
                        key=f"aj_nome_{pedido}"
                    )

                    if novo_nome and novo_nome != pedido:
                        pedidos.loc[
                            pedidos["pedido"] == pedido,
                            "pedido"
                        ] = novo_nome

                        itens.loc[
                            itens["pedido"] == pedido,
                            "pedido"
                        ] = novo_nome

                        pedido = novo_nome

                    st.divider()

                    # =================================================
                    # 📦 ITENS DO PEDIDO (EDITAR / REMOVER)
                    # =================================================
                    itens_p = itens[itens["pedido"] == pedido].copy()

                    if itens_p.empty:
                        st.info("Pedido sem itens.")
                    else:
                        for idx, it in itens_p.iterrows():
                            c1, c2, c3, c4 = st.columns([2, 4, 2, 1])

                            c1.markdown(f"**{it['sku']}**")
                            c2.write(it["descricao"])

                            nova_qtd = c3.number_input(
                                "Qtd",
                                min_value=0,
                                value=int(it["quantidade"]),
                                key=f"aj_qtd_{pedido}_{idx}"
                            )

                            itens.loc[idx, "quantidade"] = int(nova_qtd)

                            if c4.button("🗑️", key=f"rem_{pedido}_{idx}"):
                                itens.drop(idx, inplace=True)
                                save_all()
                                st.rerun()

                    st.divider()

                    # =================================================
                    # ➕ ADICIONAR ITEM (BUSCA POR SKU OU NOME)
                    # =================================================
                    st.subheader("➕ Adicionar item")

                    termo = st.text_input(
                        "Buscar por SKU ou descrição",
                        key=f"busca_prod_{pedido}"
                    )

                    if termo:
                        filtro = produtos[
                            produtos["sku"].astype(str).str.contains(
                                termo, case=False, na=False
                            ) |
                            produtos["descricao"].astype(str).str.contains(
                                termo, case=False, na=False
                            )
                        ]

                        if filtro.empty:
                            st.warning("Nenhum produto encontrado.")
                        else:
                            for _, prod in filtro.iterrows():
                                c1, c2, c3 = st.columns([2, 5, 2])

                                c1.markdown(f"**{prod['sku']}**")
                                c2.write(prod["descricao"])

                                qtd_add = c3.number_input(
                                    "Qtd",
                                    min_value=1,
                                    step=1,
                                    key=f"add_qtd_{pedido}_{prod['sku']}"
                                )

                                if c3.button("➕", key=f"add_{pedido}_{prod['sku']}"):
                                    itens.loc[len(itens)] = [
                                        pedido,
                                        prod["sku"],
                                        prod["descricao"],
                                        int(qtd_add)
                                    ]
                                    save_all()
                                    st.rerun()

                    st.divider()

                    # =================================================
                    # 🔙 RETORNAR STATUS ORIGINAL
                    # =================================================
                    if st.button("🔙 RETORNAR STATUS", key=f"ret_aj_{pedido}"):
                        registrar_historico(
                            pedido,
                            "AJUSTE FINALIZADO",
                            f"Pedido ajustado e retornado para {status_origem}"
                        )

                        pedidos.loc[
                            pedidos["pedido"] == pedido,
                            "status"
                        ] = status_origem

                        pedidos.loc[
                            pedidos["pedido"] == pedido,
                            "dados_fin"
                        ] = ""

                        save_all()
                        st.success("Pedido devolvido ao fluxo normal.")
                        st.rerun()
# =====================================================
# MÓDULO 9 — 🗂️ GERENCIADOR
# =====================================================

if menu == "🗂️ Gerenciador":
    st.title("🗂️ Gerenciador")

    status_lista = [
        "TODOS", "ABERTO", "SEPARACAO", "MONTAGEM",
        "OCORRENCIA", "ANALISAR", "ENTRADA", "SAIDA", "FINALIZADO"
    ]

    # ========================
    # FILTROS
    # ========================
    colf1, colf2 = st.columns(2)

    with colf1:
        filtro_status = st.selectbox("Status", status_lista)

    with colf2:
        busca = st.text_input("🔍 Buscar pedido ou SKU").lower().strip()

    pedidos_vis = pedidos.copy()

    # ---------------- FILTRO STATUS ----------------
    if filtro_status != "TODOS":
        pedidos_vis = pedidos_vis[pedidos_vis["status"] == filtro_status]

    # ---------------- FILTRO BUSCA ----------------
    if busca:
        achados = []
        for _, p in pedidos_vis.iterrows():
            texto = str(p["pedido"]).lower()
            itens_p = itens[itens["pedido"] == p["pedido"]]
            texto += " ".join(itens_p["sku"].astype(str)).lower()
            if busca in texto:
                achados.append(p["pedido"])

        pedidos_vis = pedidos_vis[pedidos_vis["pedido"].isin(achados)]

    if pedidos_vis.empty:
        st.info("Nenhum pedido encontrado.")
        st.stop()

    # ========================
    # LISTAGEM DOS PEDIDOS
    # ========================
    for idx, p in pedidos_vis.iterrows():
        pedido = p["pedido"]
        status = p["status"]

        cor = {
            "ABERTO": "#546e7a",
            "SEPARACAO": "#1e88e5",
            "MONTAGEM": "#1976d2",
            "OCORRENCIA": "#e53935",
            "ANALISAR": "#fb8c00",
            "ENTRADA": "#9e9e9e",
            "SAIDA": "#7b1fa2",
            "FINALIZADO": "#43a047",
            "AJUSTE": "#e91e63"
        }.get(status, "#999")

        with st.expander(f"🧾 {pedido}"):

            # ---------- BADGE STATUS ----------
            st.markdown(
                f"""
                <div style="
                    float:right;
                    background:{cor};
                    color:white;
                    padding:4px 10px;
                    border-radius:999px;
                    font-size:12px;
                    font-weight:700;
                    margin-top:-28px;
                ">
                    {status}
                </div>
                """,
                unsafe_allow_html=True
            )

            # ========================
            # ITENS DO PEDIDO (QTD INICIAL x ATUAL)
            # ========================
            itens_pedido = itens[itens["pedido"] == pedido].copy()

            if not itens_pedido.empty:

                # garante quantidade inicial
                if "quantidade_inicial" not in itens_pedido.columns:
                    itens_pedido["quantidade_inicial"] = (
                        itens_pedido
                        .groupby("sku")["quantidade"]
                        .transform("first")
                    )

                tabela_qtd = itens_pedido[
                    ["sku", "descricao", "quantidade_inicial", "quantidade"]
                ].rename(columns={
                    "quantidade": "quantidade_atual"
                })

                st.dataframe(
                    tabela_qtd,
                    hide_index=True,
                    use_container_width=True
                )
            else:
                st.info("Nenhum item registrado neste pedido.")

            st.divider()

            # ========================
            # ALTERAR STATUS
            # ========================
            novos_status = [s for s in status_lista[1:] if s != status]

            novo = st.selectbox(
                "Alterar status do pedido:",
                novos_status,
                key=f"ger_status_{pedido}_{idx}"
            )

            if st.button("🔁 ALTERAR STATUS", key=f"ger_btn_{pedido}_{idx}"):

                pedidos.loc[
                    pedidos["pedido"] == pedido,
                    "status"
                ] = novo

                registrar_historico(
                    pedido,
                    "ALTERAÇÃO STATUS",
                    f"Status alterado de {status} para {novo}"
                )

                save_all()
                st.rerun()

            st.divider()

            # ========================
            # REMOVER PEDIDO (TOTAL)
            # ========================
            if st.button(
                "🗑️ REMOVER PEDIDO (IRREVERSÍVEL)",
                key=f"del_{pedido}_{idx}"
            ):

                pedidos.drop(
                    pedidos[pedidos["pedido"] == pedido].index,
                    inplace=True
                )

                itens.drop(
                    itens[itens["pedido"] == pedido].index,
                    inplace=True
                )

                movs.drop(
                    movs[movs["pedido"] == pedido].index,
                    inplace=True
                )

                registrar_historico(
                    pedido,
                    "REMOVIDO",
                    "Pedido removido completamente do sistema"
                )

                st.session_state.get("itens_editados", {}).pop(pedido, None)

                save_all()
                st.rerun()
# =====================================================
# MÓDULO 10 — 📍 ACOMPANHAR FLUXO
# =====================================================

if menu == "📍 Acompanhar Fluxo":
    st.title("📍 Acompanhar Fluxo")

    # ========================
    # FILTROS
    # ========================
    colf1, colf2 = st.columns([1, 2])

    with colf1:
        filtro_status = st.selectbox(
            "Status",
            ["TODOS"] + sorted(
                pedidos["status"]
                .dropna()
                .astype(str)
                .unique()
                .tolist()
            )
        )

    with colf2:
        busca = st.text_input("🔍 Buscar por Pedido ou SKU").lower().strip()

    pedidos_vis = pedidos.copy()

    # ---------------- FILTRO STATUS ----------------
    if filtro_status != "TODOS":
        pedidos_vis = pedidos_vis[pedidos_vis["status"] == filtro_status]

    # ---------------- FILTRO BUSCA ----------------
    if busca:
        achados = []
        for _, p in pedidos_vis.iterrows():
            nome = str(p["pedido"]).lower()
            itens_p = itens[itens["pedido"] == p["pedido"]]
            skus = " ".join(itens_p["sku"].astype(str).str.lower())
            if busca in nome or busca in skus:
                achados.append(p["pedido"])

        pedidos_vis = pedidos_vis[pedidos_vis["pedido"].isin(achados)]

    if pedidos_vis.empty:
        st.info("Nenhum pedido encontrado.")
        st.stop()

    # ========================
    # CONTROLE DE VISUALIZAÇÃO
    # ========================
    st.session_state.setdefault("fluxo_view", {})

    # ========================
    # LISTAGEM DOS PEDIDOS
    # ========================
    for _, p in pedidos_vis.iterrows():
        pedido = p["pedido"]
        status = str(p["status"]).upper()

        cor = {
            "ABERTO": "#546e7a",
            "SEPARACAO": "#1e88e5",
            "MONTAGEM": "#1976d2",
            "OCORRENCIA": "#e53935",
            "ANALISAR": "#fb8c00",
            "ENTRADA": "#9e9e9e",
            "SAIDA": "#7b1fa2",
            "FINALIZADO": "#43a047",
            "AJUSTE": "#e91e63"
        }.get(status, "#999")

        with st.expander(f"🧾 {pedido}"):

            # ========================
            # BADGE STATUS
            # ========================
            st.markdown(
                f"""
                <div style="
                    float:right;
                    background:{cor};
                    color:white;
                    padding:4px 12px;
                    border-radius:999px;
                    font-size:12px;
                    font-weight:700;
                    margin-top:-28px;
                ">
                    {status}
                </div>
                """,
                unsafe_allow_html=True
            )

            # ========================
            # BLOQUEIO TOTAL
            # ========================
            if status == "AJUSTE":
                st.warning("⏳ AGUARDANDO ANÁLISE")
                continue

            # ========================
            # ITENS DO PEDIDO (LEITURA)
            # ========================
            itens_p = itens[itens["pedido"] == pedido]

            linhas = []
            for _, it in itens_p.iterrows():
                linhas.append({
                    "SKU": it["sku"],
                    "Descrição": it["descricao"],
                    "Quantidade": int(it["quantidade"])
                })

            st.dataframe(
                pd.DataFrame(linhas),
                hide_index=True,
                use_container_width=True
            )

            st.divider()

            # ========================
            # BOTÕES HISTÓRICO / AJUDA
            # ========================
            st.session_state["fluxo_view"].setdefault(pedido, None)

            colb1, colb2 = st.columns(2)

            if colb1.button("📜 Histórico", key=f"hist_{pedido}"):
                st.session_state["fluxo_view"][pedido] = "HIST"

            if colb2.button("❗ Ajuda", key=f"help_{pedido}"):
                st.session_state["fluxo_view"][pedido] = "HELP"

            # ========================
            # HISTÓRICO (COM RESPONSÁVEL)
            # ========================
            if st.session_state["fluxo_view"][pedido] == "HIST":
                hist_p = hist[hist["pedido"] == pedido]

                if hist_p.empty:
                    st.info("Sem histórico.")
                else:
                    hist_p = hist_p.sort_values("data", ascending=False)

                    st.dataframe(
                        hist_p[[
                            "data",
                            "acao",
                            "detalhe",
                            "responsavel"
                        ]].rename(columns={
                            "data": "Data",
                            "acao": "Ação",
                            "detalhe": "Detalhe",
                            "responsavel": "Responsável"
                        }),
                        hide_index=True,
                        use_container_width=True
                    )

            # ========================
            # AJUDA / SOLICITAR AJUSTE
            # ========================
            if st.session_state["fluxo_view"][pedido] == "HELP":
                comentario = st.text_area(
                    "Descreva o ajuste necessário",
                    key=f"aj_com_{pedido}"
                )

                if st.button("📨 Enviar para Análise", key=f"send_adj_{pedido}"):
                    if not comentario:
                        st.error("Informe o comentário.")
                        st.stop()

                    registrar_historico(
                        pedido,
                        "SOLICITAÇÃO DE AJUSTE",
                        comentario
                    )

                    pedidos.loc[
                        pedidos["pedido"] == pedido,
                        "dados_fin"
                    ] = json.dumps({
                        "status_origem": status,
                        "comentario_ajuste": comentario
                    })

                    pedidos.loc[
                        pedidos["pedido"] == pedido,
                        "status"
                    ] = "AJUSTE"

                    save_all()
                    st.success("Pedido enviado para ajuste.")
                    st.rerun()
# =====================================================
# MÓDULO — 👤 USUÁRIOS
# =====================================================
if menu == "👤 Usuários":

    # 🔒 PROTEÇÃO
    if st.session_state.get("perfil") != "ANALISTA":
        st.error("Acesso restrito.")
        st.stop()

    st.title("👤 Usuários do Sistema")

    conn = get_conn()
    usuarios_df = pd.read_sql(
        "SELECT id, usuario, perfil, ativo, criado_em FROM usuarios",
        conn
    )
    conn.close()

    # =================================================
    # ➕ CRIAR USUÁRIO
    # =================================================
    with st.expander("➕ Criar novo usuário"):
        with st.form("form_novo_usuario"):
            usuario = st.text_input("Usuário")
            senha = st.text_input("Senha", type="password")
            perfil = st.selectbox(
                "Perfil",
                ["ANALISTA", "INNOVA", "ESTOQUE", "PRODUTO"]
            )

            if st.form_submit_button("Criar"):
                if not usuario or not senha:
                    st.error("Usuário e senha são obrigatórios.")
                else:
                    ok = criar_usuario(usuario, senha, perfil)
                    if ok:
                        st.success("Usuário criado com sucesso.")
                        st.rerun()
                    else:
                        st.error("Usuário já existe.")

    st.divider()

    # =================================================
    # 📋 LISTAGEM DE USUÁRIOS
    # =================================================
    if usuarios_df.empty:
        st.info("Nenhum usuário cadastrado.")
        st.stop()

    for _, u in usuarios_df.iterrows():

        status = "🟢 Ativo" if u["ativo"] == 1 else "🔴 Inativo"

        with st.expander(f"{u['usuario']} — {u['perfil']} — {status}"):

            col1, col2 = st.columns(2)

            # -------- PERFIL --------
            with col1:
                novo_perfil = st.selectbox(
                    "Perfil",
                    ["ANALISTA", "INNOVA", "ESTOQUE", "PRODUTO"],
                    index=["ANALISTA", "INNOVA", "ESTOQUE", "PRODUTO"].index(u["perfil"]),
                    key=f"perfil_{u['id']}"
                )

                if st.button("💾 Atualizar perfil", key=f"upd_p_{u['id']}"):
                    conn = get_conn()
                    conn.execute(
                        "UPDATE usuarios SET perfil=? WHERE id=?",
                        (novo_perfil, u["id"])
                    )
                    conn.commit()
                    conn.close()
                    st.success("Perfil atualizado.")
                    st.rerun()

            # -------- ATIVO / INATIVO --------
            with col2:
                novo_status = 0 if u["ativo"] == 1 else 1
                texto = "🚫 Desativar" if u["ativo"] == 1 else "✅ Ativar"

                if st.button(texto, key=f"stat_{u['id']}"):
                    conn = get_conn()
                    conn.execute(
                        "UPDATE usuarios SET ativo=? WHERE id=?",
                        (novo_status, u["id"])
                    )
                    conn.commit()
                    conn.close()
                    st.success("Status alterado.")
                    st.rerun()

            st.divider()

            # -------- ALTERAR SENHA --------
            nova_senha = st.text_input(
                "Nova senha",
                type="password",
                key=f"senha_{u['id']}"
            )

            if st.button("🔑 Alterar senha", key=f"alt_s_{u['id']}"):
                if not nova_senha:
                    st.error("Informe a senha.")
                else:
                    conn = get_conn()
                    conn.execute(
                        "UPDATE usuarios SET senha=? WHERE id=?",
                        (hash_senha(nova_senha), u["id"])
                    )
                    conn.commit()
                    conn.close()
                    st.success("Senha alterada.")
                    st.rerun()

            st.divider()

            # -------- REMOVER --------
            if st.button("🗑️ Remover usuário", key=f"del_{u['id']}"):
                if u["usuario"] == st.session_state["usuario"]:
                    st.error("Você não pode remover seu próprio usuário.")
                else:
                    conn = get_conn()
                    conn.execute(
                        "DELETE FROM usuarios WHERE id=?",
                        (u["id"],)
                    )
                    conn.commit()
                    conn.close()
                    st.success("Usuário removido.")
                    st.rerun()

