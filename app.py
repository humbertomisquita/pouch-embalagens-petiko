# =====================================================
# BLOCO 1 + BLOCO 2 — BASE FUNCIONAL GLOBAL + BANCO
# (POSTGRESQL / SUPABASE)
# =====================================================

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
import hashlib

# ========================
# CONFIG STREAMLIT
# ========================
st.set_page_config(layout="wide")

# ========================
# CONEXÃO POSTGRES (SUPABASE)
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
# TESTE DE CONEXÃO
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

    cur.execute("""
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

init_db()

# ========================
# FUNÇÕES — LEITURA
# ========================
def ler_tabela(nome):
    conn = get_conn()
    df = pd.read_sql(f"SELECT * FROM {nome}", conn)
    conn.close()
    return df

# ========================
# FUNÇÕES — SALVAR (SIMULA SQLite)
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

produtos = garantir_colunas(produtos, ["sku", "descricao", "quantidade", "localizacao"])
pedidos  = garantir_colunas(pedidos, ["pedido", "data", "status", "dados_fin"])
itens    = garantir_colunas(itens, ["pedido", "sku", "descricao", "quantidade"])
movs     = garantir_colunas(movs, ["data", "sku", "descricao", "tipo", "quantidade", "pedido", "obs"])
hist     = garantir_colunas(hist, ["pedido", "data", "acao", "detalhe", "responsavel"])

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
    raw = pedidos.loc[pedidos["pedido"] == pedido, "dados_fin"].values
    if raw.size == 0 or pd.isna(raw[0]) or str(raw[0]).strip() == "":
        return {}
    try:
        return json.loads(str(raw[0]))
    except:
        return {}

# ========================
# HISTÓRICO
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
    return None if f.empty else f.iloc[-1]["detalhe"]

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
# USUÁRIOS — FUNÇÕES BASE
# ========================
def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

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
        ok = True
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        ok = False
    conn.close()
    return ok

def validar_login(usuario, senha):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT usuario, perfil
        FROM usuarios
        WHERE usuario = %s
          AND senha = %s
          AND ativo = 1
    """, (usuario, hash_senha(senha)))
    row = c.fetchone()
    conn.close()
    return None if not row else {"usuario": row[0], "perfil": row[1]}

def alterar_senha(usuario, nova_senha):
    conn = get_conn()
    conn.cursor().execute(
        "UPDATE usuarios SET senha=%s WHERE usuario=%s AND ativo=1",
        (hash_senha(nova_senha), usuario)
    )
    conn.commit()
    conn.close()

# Usuário inicial (idempotente)
criar_usuario("humberto", "1234", "ANALISTA")

# ========================
# SESSION STATE BASE
# ========================
st.session_state.setdefault("modo", None)
st.session_state.setdefault("menu", None)
# =====================================================
# BLOCO 2 — BASE DE DADOS (POSTGRESQL / SUPABASE)
# =====================================================

# =====================================================
# INIT DB — CRIA TODAS AS TABELAS
# =====================================================
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # ---------------- PRODUTOS ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            sku TEXT PRIMARY KEY,
            descricao TEXT,
            quantidade INTEGER,
            localizacao TEXT
        )
    """)

    # ---------------- PEDIDOS ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pedidos (
            pedido TEXT PRIMARY KEY,
            data TEXT,
            status TEXT,
            dados_fin TEXT
        )
    """)

    # ---------------- ITENS DO PEDIDO ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS itens_pedido (
            id SERIAL PRIMARY KEY,
            pedido TEXT,
            sku TEXT,
            descricao TEXT,
            quantidade INTEGER
        )
    """)

    # ---------------- MOVIMENTAÇÕES ----------------
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

    # ---------------- HISTÓRICO ----------------
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

    # ---------------- USUÁRIOS ----------------
    cur.execute("""
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

# Executa na inicialização
init_db()

# =====================================================
# LEITURA DE TABELA (POSTGRES → DATAFRAME)
# =====================================================
def ler_tabela(nome):
    conn = get_conn()
    df = pd.read_sql(f"SELECT * FROM {nome}", conn)
    conn.close()
    return df

# =====================================================
# SALVAR TABELA (REPLACE TOTAL — MESMO COMPORTAMENTO DO SQLITE)
# =====================================================
def salvar_tabela(nome, df):
    conn = get_conn()
    cur = conn.cursor()

    # limpa a tabela
    cur.execute(f"DELETE FROM {nome}")

    if not df.empty:
        colunas = list(df.columns)
        placeholders = ", ".join(["%s"] * len(colunas))
        nomes = ", ".join(colunas)

        for _, row in df.iterrows():
            cur.execute(
                f"INSERT INTO {nome} ({nomes}) VALUES ({placeholders})",
                tuple(row.values)
            )

    conn.commit()
    conn.close()

# =====================================================
# SAVE GLOBAL (USADO PELO SISTEMA TODO)
# =====================================================
def save_all():
    salvar_tabela("produtos", produtos)
    salvar_tabela("pedidos", pedidos)
    salvar_tabela("itens_pedido", itens)
    salvar_tabela("movimentacoes", movs)
    salvar_tabela("historico_pedidos", hist)
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
/* === TODO O CSS ORIGINAL — SEM ALTERAÇÃO === */
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
# 🔁 MIGRAÇÃO POSTGRES
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
# 🔁 MIGRAÇÃO POSTGRES
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
# 🔁 MIGRAÇÃO POSTGRES
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
        return {
            "usuario": row[0],
            "perfil": row[1]
        }

    return None

# =====================================================
# ALTERAR SENHA DO PRÓPRIO USUÁRIO
# 🔁 MIGRAÇÃO POSTGRES
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
# GARANTE TABELA E CRIA USUÁRIO TESTE (IDEMPOTENTE)
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
# CONTROLE DE ACESSO POR PERFIL (INALTERADO)
# =====================================================
PERMISSOES = {
    "ANALISTA": [
        "📦 Produtos", "🧾 Pedidos", "📋 Estoque", "🏭 Innova",
        "🕵️ Analista", "🗂️ Gerenciador", "📍 Acompanhar Fluxo", "👤 Usuários"
    ],
    "PRODUTO": [
        "📦 Produtos", "🧾 Pedidos", "📍 Acompanhar Fluxo"
    ],
    "ESTOQUE": [
        "📦 Produtos", "📋 Estoque", "📍 Acompanhar Fluxo"
    ],
    "INNOVA": [
        "🏭 Innova", "📍 Acompanhar Fluxo"
    ]
}

# -------- RODAPÉ FIXO DA SIDEBAR --------
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
