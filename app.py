# =====================================================
# MÓDULO 1 — BASE FUNCIONAL GLOBAL (POSTGRES)
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

# =====================================================
# SESSION STATE BASE
# =====================================================
st.session_state.setdefault("bloquear_cookie", False)
st.session_state.setdefault("modo", None)
st.session_state.setdefault("menu", None)

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

# =====================================================
# POSTGRES — CONEXÃO ÚNICA
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
# LEITURA DE TABELA (POSTGRES)
# =====================================================
def ler_tabela(nome):
    conn = get_conn()
    try:
        df = pd.read_sql(f"SELECT * FROM {nome}", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df

# =====================================================
# LOAD GLOBAL (OBRIGATÓRIO — MANTIDO)
# =====================================================
produtos = ler_tabela("produtos")
pedidos  = ler_tabela("pedidos")
itens    = ler_tabela("itens_pedido")
movs     = ler_tabela("movimentacoes")
hist     = ler_tabela("historico_pedidos")

# =====================================================
# GARANTE COLUNAS (ANTI-ERRO — ORIGINAL)
# =====================================================
def garantir_colunas(df, colunas):
    for c in colunas:
        if c not in df.columns:
            df[c] = ""
    return df

produtos = garantir_colunas(
    produtos,
    ["sku", "descricao", "categoria", "quantidade", "localizacao"]
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

# =====================================================
# LEITURA SEGURA dados_fin (INALTERADO)
# =====================================================
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

# =====================================================
# STATUS COLORS (GLOBAL — ORIGINAL)
# =====================================================
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
# =====================================================
# MÓDULO 2 — 👤 USUÁRIOS + LOGIN + MENU (POSTGRES)
# =====================================================

import hashlib

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
    cur = conn.cursor()

    try:
        cur.execute("""
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
    cur = conn.cursor()

    cur.execute("""
        SELECT usuario, perfil
        FROM usuarios
        WHERE usuario = %s
          AND senha = %s
          AND ativo = 1
    """, (
        usuario,
        hash_senha(senha)
    ))

    row = cur.fetchone()
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
    cur = conn.cursor()

    cur.execute("""
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
# GARANTE USUÁRIO PADRÃO (RODA UMA VEZ)
# =====================================================
conn = get_conn()
cur = conn.cursor()

cur.execute("SELECT 1 FROM usuarios WHERE usuario = %s", ("humberto",))
existe = cur.fetchone()

if not existe:
    cur.execute("""
        INSERT INTO usuarios (usuario, senha, perfil, ativo, criado_em)
        VALUES (%s, %s, %s, 1, %s)
    """, (
        "humberto",
        hash_senha("1234"),
        "ANALISTA",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()

conn.close()

# =====================================================
# LOGOUT
# =====================================================
def logout():
    st.session_state["logado"] = False
    st.session_state["usuario"] = None
    st.session_state["perfil"] = None
    st.rerun()

# =====================================================
# TELA DE LOGIN
# =====================================================
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

# =====================================================
# BLOQUEIO GLOBAL
# =====================================================
if not st.session_state["logado"]:
    tela_login()
    st.stop()

# =====================================================
# PERMISSÕES POR PERFIL (INALTERADO)
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

# =====================================================
# SIDEBAR — MENU + LOGOUT (INALTERADO)
# =====================================================
with st.sidebar:

    if "logado" not in st.session_state or not st.session_state.get("logado"):
        st.warning("Sessão expirada. Faça login novamente.")
        st.stop()

    perfil = st.session_state.get("perfil")
    menu_opcoes = PERMISSOES_MENU.get(perfil, [])

    escolha = st.radio(
        "Menu",
        menu_opcoes,
        key="menu_radio"
    )

    st.session_state["menu"] = escolha

    st.divider()

    if st.button("🚪 Logout", use_container_width=True):
        st.session_state["bloquear_cookie"] = True

        cookies["logado"] = ""
        cookies["usuario"] = ""
        cookies["perfil"] = ""
        cookies.save()

        st.session_state["logado"] = False
        st.session_state["usuario"] = None
        st.session_state["perfil"] = None

        st.rerun()

# =====================================================
# VARIÁVEL GLOBAL USADA PELO SISTEMA
# =====================================================
menu = st.session_state["menu"]
# =====================================================
# MÓDULO 4 — 📦 PRODUTOS (POSTGRES)
# =====================================================

if menu == "📦 Produtos":
    st.title("📦 PRODUTOS")

    # =================================================
    # RECARREGA PRODUTOS DO BANCO (FONTE DA VERDADE)
    # =================================================
    produtos = ler_tabela("produtos")

    # =================================================
    # NORMALIZAÇÃO DE SCHEMA (ANTI-ERRO — ORIGINAL)
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
                    conn = get_conn()
                    cur = conn.cursor()

                    cur.execute("""
                        INSERT INTO produtos (sku, descricao, categoria, quantidade, localizacao)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        sku, desc, categoria, int(qtd), loc
                    ))

                    cur.execute("""
                        INSERT INTO movimentacoes
                        (data, sku, descricao, tipo, quantidade, pedido, obs)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        datetime.now().strftime("%d/%m/%Y %H:%M"),
                        sku,
                        desc,
                        "ENTRADA",
                        int(qtd),
                        "",
                        "Cadastro inicial"
                    ))

                    conn.commit()
                    conn.close()

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
    # 🎨 ESTILOS DOS CARDS (INALTERADO)
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

            conn = get_conn()
            cur = conn.cursor()

            if acao == "ENTRADA":
                valor = st.number_input("Quantidade", min_value=1, step=1, key=f"ent_{sku}")
                obs = st.text_input("Obs", key=f"obs_ent_{sku}")
                if st.button("Confirmar", key=f"conf_ent_{sku}"):
                    cur.execute("""
                        UPDATE produtos
                        SET quantidade = quantidade + %s
                        WHERE sku = %s
                    """, (int(valor), sku))

                    cur.execute("""
                        INSERT INTO movimentacoes
                        (data, sku, descricao, tipo, quantidade, pedido, obs)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        datetime.now().strftime("%d/%m/%Y %H:%M"),
                        sku, p["descricao"], "ENTRADA",
                        int(valor), "", obs
                    ))

                    conn.commit()
                    conn.close()
                    st.rerun()

            if acao == "SAIDA":
                valor = st.number_input("Quantidade", min_value=1, step=1, key=f"sai_{sku}")
                obs = st.text_input("Obs", key=f"obs_sai_{sku}")
                if st.button("Confirmar", key=f"conf_sai_{sku}"):
                    if p["quantidade"] >= valor:
                        cur.execute("""
                            UPDATE produtos
                            SET quantidade = quantidade - %s
                            WHERE sku = %s
                        """, (int(valor), sku))

                        cur.execute("""
                            INSERT INTO movimentacoes
                            (data, sku, descricao, tipo, quantidade, pedido, obs)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (
                            datetime.now().strftime("%d/%m/%Y %H:%M"),
                            sku, p["descricao"], "SAIDA",
                            int(valor), "", obs
                        ))

                        conn.commit()
                        conn.close()
                        st.rerun()
                    else:
                        conn.close()
                        st.error("Quantidade insuficiente.")

            if acao == "EDITAR":
                desc_novo = st.text_input("Descrição", p["descricao"], key=f"d_{sku}")
                loc_novo = st.text_input("Localização", p["localizacao"], key=f"l_{sku}")
                if st.button("Salvar alterações", key=f"save_{sku}"):
                    cur.execute("""
                        UPDATE produtos
                        SET descricao = %s, localizacao = %s
                        WHERE sku = %s
                    """, (desc_novo, loc_novo, sku))
                    conn.commit()
                    conn.close()
                    st.rerun()

            if acao == "HIST":
                conn.close()
                hist_p = pd.read_sql(
                    "SELECT * FROM movimentacoes WHERE sku = %s ORDER BY id DESC",
                    get_conn(),
                    params=(sku,)
                )
                st.dataframe(hist_p, hide_index=True, use_container_width=True)

            if acao == "DEL":
                st.warning("Essa ação não pode ser desfeita.")
                if st.button("Confirmar exclusão", key=f"del_conf_{sku}"):
                    cur.execute("DELETE FROM produtos WHERE sku = %s", (sku,))
                    cur.execute("DELETE FROM movimentacoes WHERE sku = %s", (sku,))
                    conn.commit()
                    conn.close()
                    st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)
