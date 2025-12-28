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
# MÓDULO 2 — BASE DE DADOS (POSTGRESQL / SUPABASE)
# =====================================================

import psycopg2
import pandas as pd
import json

# =====================================================
# CONEXÃO ÚNICA
# =====================================================
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

# =====================================================
# CRIA TABELAS (SCHEMA IDÊNTICO AO SQLITE)
# =====================================================
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            sku TEXT PRIMARY KEY,
            descricao TEXT,
            categoria TEXT,
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

# =====================================================
# LEITURA DE TABELA (RETORNA DATAFRAME)
# =====================================================
def ler_tabela(nome):
    conn = get_conn()
    df = pd.read_sql(f"SELECT * FROM {nome}", conn)
    conn.close()
    return df

# =====================================================
# SALVA DATAFRAME (REPLACE TOTAL — IGUAL AO SQLITE)
# =====================================================
def salvar_tabela(nome, df):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(f"DELETE FROM {nome}")

    if not df.empty:
        cols = list(df.columns)
        valores = [tuple(x) for x in df.to_numpy()]

        placeholders = ",".join(["%s"] * len(cols))
        colunas = ",".join(cols)

        cur.executemany(
            f"INSERT INTO {nome} ({colunas}) VALUES ({placeholders})",
            valores
        )

    conn.commit()
    conn.close()

# =====================================================
# SAVE GLOBAL (IDÊNTICO AO ORIGINAL)
# =====================================================
def save_all():
    salvar_tabela("produtos", produtos)
    salvar_tabela("pedidos", pedidos)
    salvar_tabela("itens_pedido", itens)
    salvar_tabela("movimentacoes", movs)
    salvar_tabela("historico_pedidos", hist)
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
# GARANTE TABELA E CRIA USUÁRIO INICIAL
# =====================================================
criar_tabela_usuarios()
criar_usuario("humberto", "1234", "ANALISTA")
