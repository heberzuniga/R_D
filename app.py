import streamlit as st
import pandas as pd
import numpy as np
import json, os, math, time
from datetime import datetime

APP_TITLE = "Misión Bonos — Simulador de Carteras (MVP)"
STATE_DIR = "games"  # carpeta local donde se guardan los estados por partida
os.makedirs(STATE_DIR, exist_ok=True)

# -------------------------------
# Utilidades de persistencia
# -------------------------------
def game_path(game_code: str) -> str:
    return os.path.join(STATE_DIR, f"{game_code}.json")

def load_state(game_code: str) -> dict:
    p = game_path(game_code)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    # estado inicial si no existe
    return {
        "game": {
            "game_code": game_code,
            "rondas_totales": 3,
            "ronda_actual": 1,
            "estado": "LOBBY",  # LOBBY | TRADING_ON | TRADING_OFF | FIN
            "fraccion_anio": 0.25,
            "bid_bp": 20,
            "ask_bp": 20,
            "comision_bps": 10,
            "created_at": datetime.utcnow().isoformat(),
            "cash_inicial": 1_000_000.0
        },
        "bonds": [],
        "events": [],
        "prices": [],
        "teams": [],
        "orders": [],
        "ledger": []
    }

def save_state(state: dict):
    p = game_path(state["game"]["game_code"])
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# -------------------------------
# Modelo financiero básico
# -------------------------------
def price_bond_mid(bond: dict, ytm_anual: float, frac_anio: float, rounds_elapsed: int) -> float:
    """DCF simple. Ajusta el tiempo a vencimiento por rondas transcurridas."""
    f = int(bond.get("frecuencia_anual", 2) or 2)
    V = float(bond.get("valor_nominal", 1000))
    cup_anual = float(bond.get("tasa_cupon_anual", 0.08))
    venc_ini = float(bond.get("vencimiento_anios", 3))
    venc_rest = max(0.0, venc_ini - rounds_elapsed * frac_anio)

    dt = 1.0 / f
    N = max(1, int(math.ceil(venc_rest / dt)))
    C = V * (cup_anual / f)
    i = ytm_anual / f

    # Evitar división por 0 si i es -1/f (caso extremo)
    pv = 0.0
    for k in range(1, N + 1):
        pv += C / ((1 + i) ** k)
    pv += V / ((1 + i) ** N)
    return max(0.01, float(pv))

def bid_ask_from_mid(mid: float, bid_bp: float, ask_bp: float):
    bid = mid * (1 - bid_bp / 10_000.0)
    ask = mid * (1 + ask_bp / 10_000.0)
    return bid, ask

def effective_ytm(spread_bps: float, delta_market_bps: float, idios_bps: float) -> float:
    """tasa_base anual = 0 en el MVP; componemos bps -> %"""
    return (spread_bps + delta_market_bps + idios_bps) / 10_000.0

# -------------------------------
# Helpers de negocio
# -------------------------------
def ensure_events_from_wizard(state: dict):
    """Si no hay eventos, proponer 3 eventos adaptativos por defecto."""
    if state["events"]:
        return
    bonds = state["bonds"]
    # Evento 1: shock de tasas +75 bps (MARKET)
    state["events"].append({
        "round": 1, "tipo": "MARKET", "bond_id": None,
        "delta_tasa_bps": 75, "impacto_bps": 0, "descripcion": "Shock de tasas global +75 bps",
        "publicado": False
    })
    # Evento 2: mejora macro -40 bps (MARKET)
    state["events"].append({
        "round": 2, "tipo": "MARKET", "bond_id": None,
        "delta_tasa_bps": -40, "impacto_bps": 0, "descripcion": "Mejora macro (-40 bps)",
        "publicado": False
    })
    # Evento 3: riesgo crédito idiosincrático +120 bps aplicado al bono con mayor spread
    bond_target = None
    if bonds:
        bond_target = max(bonds, key=lambda b: float(b.get("spread_bps", 0)))
    state["events"].append({
        "round": 3, "tipo": "IDIOS", "bond_id": (bond_target.get("bond_id") if bond_target else "B1"),
        "delta_tasa_bps": 0, "impacto_bps": 120, "descripcion": "Riesgo crédito específico +120 bps",
        "publicado": False
    })

def publish_prices_for_round(state: dict):
    g = state["game"]
    r = int(g["ronda_actual"])
    frac = float(g["fraccion_anio"])
    bid_bp = float(g["bid_bp"])
    ask_bp = float(g["ask_bp"])

    # Eventos de la ronda
    ev_mkt = sum(e.get("delta_tasa_bps", 0) for e in state["events"] if e["round"] == r and e["tipo"] == "MARKET")
    # Generamos precios por bono
    new_prices = []
    for b in state["bonds"]:
        idios = sum(e.get("impacto_bps", 0) for e in state["events"]
                    if e["round"] == r and e["tipo"] == "IDIOS" and str(e.get("bond_id")) == str(b.get("bond_id")))
        ytm = effective_ytm(float(b.get("spread_bps", 0)), float(ev_mkt), float(idios))
        mid = price_bond_mid(b, ytm, frac_anio=frac, rounds_elapsed=r-1)
        bid, ask = bid_ask_from_mid(mid, bid_bp, ask_bp)
        new_prices.append({
            "ronda": r,
            "bond_id": str(b.get("bond_id")),
            "y_efectiva": ytm,
            "precio_mid": mid,
            "precio_bid": bid,
            "precio_ask": ask,
            "ts_publicacion": datetime.utcnow().isoformat()
        })
    # Marcar eventos round como publicados
    for e in state["events"]:
        if e["round"] == r:
            e["publicado"] = True
    # Reemplazar precios de esa ronda
    state["prices"] = [p for p in state["prices"] if p["ronda"] != r] + new_prices
    # Cambiar estado a TRADING_ON
    g["estado"] = "TRADING_ON"

def get_prices_dict(state: dict, ronda: int) -> dict:
    """Devuelve diccionario bond_id -> precio_mid"""
    return {p["bond_id"]: p["precio_mid"] for p in state["prices"] if p["ronda"] == ronda}

def team_get(state: dict, team_name: str) -> dict | None:
    for t in state["teams"]:
        if t["team_name"] == team_name:
            return t
    return None

def team_register(state: dict, team_name: str, pin: str | None):
    if team_get(state, team_name):
        return False, "El equipo ya existe."
    cash0 = float(state["game"]["cash_inicial"])
    team = {
        "team_id": f"T{len(state['teams'])+1}",
        "team_name": team_name,
        "pin": pin or "",
        "activo": True,
        "created_at": datetime.utcnow().isoformat(),
        "cash_inicial": cash0
    }
    state["teams"].append(team)
    return True, f"Equipo {team_name} creado con {cash0:,.2f} de cash inicial."

def team_positions_and_cash(state: dict, team_name: str) -> tuple[dict, float]:
    """Reconstruye posiciones y cash desde Orders y Ledger."""
    team = team_get(state, team_name)
    if not team:
        return {}, 0.0
    pos = {}  # bond_id -> qty
    cash = float(team.get("cash_inicial", 0.0))
    # ledger
    for l in state["ledger"]:
        if l["team_id"] == team["team_id"]:
            cash += float(l.get("cash_delta", 0))
    # orders
    for o in state["orders"]:
        if o["team_id"] != team["team_id"]:
            continue
        qty = float(o.get("qty", 0))
        px = float(o.get("price_exec", 0))
        fees = float(o.get("fees", 0))
        if o["side"] == "BUY":
            pos[o["bond_id"]] = pos.get(o["bond_id"], 0.0) + qty
            cash -= qty * px + fees
        else:  # SELL
            pos[o["bond_id"]] = pos.get(o["bond_id"], 0.0) - qty
            cash += qty * px - fees
    return pos, cash

def can_exec_order(state: dict, team_name: str, side: str, bond_id: str, qty: float) -> tuple[bool, str, float, float]:
    g = state["game"]
    r = int(g["ronda_actual"])
    # precio exec
    p = next((p for p in state["prices"] if p["ronda"] == r and p["bond_id"] == bond_id), None)
    if not p:
        return False, "No hay precios publicados para este bono/ronda.", 0.0, 0.0
    px_exec = p["precio_ask"] if side == "BUY" else p["precio_bid"]
    # fees
    fees_bps = float(g["comision_bps"])
    fees = (qty * px_exec) * (fees_bps / 10_000.0)
    # posiciones/cash
    pos, cash = team_positions_and_cash(state, team_name)
    if side == "BUY":
        if cash < qty * px_exec + fees:
            return False, "Cash insuficiente.", px_exec, fees
    else:  # SELL
        if pos.get(bond_id, 0.0) < qty:
            return False, "No posee cantidad suficiente para vender.", px_exec, fees
    return True, "OK", px_exec, fees

def exec_order(state: dict, team_name: str, side: str, bond_id: str, qty: float):
    ok, msg, px_exec, fees = can_exec_order(state, team_name, side, bond_id, qty)
    if not ok:
        return False, msg
    team = team_get(state, team_name)
    state["orders"].append({
        "ts": datetime.utcnow().isoformat(),
        "team_id": team["team_id"],
        "bond_id": bond_id,
        "side": side,
        "qty": float(qty),
        "price_exec": float(px_exec),
        "fees": float(fees),
        "ronda": int(state["game"]["ronda_actual"])
    })
    return True, f"Orden {side} {qty} {bond_id} @ {px_exec:,.2f} (fees {fees:,.2f}) ejecutada."

def compute_leaderboard(state: dict, ronda: int | None = None) -> pd.DataFrame:
    if ronda is None:
        ronda = int(state["game"]["ronda_actual"])
    prices_mid = get_prices_dict(state, ronda)
    rows = []
    for t in state["teams"]:
        pos, cash = team_positions_and_cash(state, t["team_name"])
        valor_pos = 0.0
        for b, q in pos.items():
            valor_pos += q * prices_mid.get(b, 0.0)
        valor = cash + valor_pos
        rows.append({
            "Equipo": t["team_name"],
            "Cash": cash,
            "Valor_Posiciones": valor_pos,
            "Valor_Portafolio": valor
        })
    if not rows:
        return pd.DataFrame(columns=["Equipo","Cash","Valor_Posiciones","Valor_Portafolio"])
    df = pd.DataFrame(rows)
    df = df.sort_values("Valor_Portafolio", ascending=False).reset_index(drop=True)
    df.index = df.index + 1
    df.index.name = "Rank"
    return df

# --------------------------------
# Ingesta de CSV de escenario
# --------------------------------
BOND_COLS = ["type","bond_id","nombre","valor_nominal","tasa_cupon_anual","frecuencia_anual",
             "vencimiento_anios","spread_bps","callable","precio_call","round","delta_tasa_bps",
             "impacto_bps","descripcion"]

def load_scenario_df(file) -> pd.DataFrame:
    try:
        df = pd.read_csv(file)
    except Exception:
        df = pd.read_csv(file, sep=";")
    # normalizamos columnas esperadas
    lower = {c: c.lower().strip() for c in df.columns}
    df.columns = [lower.get(c, c).lower().strip() for c in df.columns]
    # aseguramos columnas faltantes
    for c in BOND_COLS:
        if c not in df.columns:
            df[c] = np.nan
    return df[BOND_COLS]

def apply_scenario_to_state(df: pd.DataFrame, state: dict):
    bonds, events = [], []
    for _, row in df.iterrows():
        t = str(row["type"]).upper()
        if t == "BOND":
            bonds.append({
                "bond_id": str(row["bond_id"]),
                "nombre": str(row["nombre"]),
                "valor_nominal": float(row.get("valor_nominal", 1000) or 1000),
                "tasa_cupon_anual": float(row.get("tasa_cupon_anual", 0.08) or 0.08),
                "frecuencia_anual": int(row.get("frecuencia_anual", 2) or 2),
                "vencimiento_anios": float(row.get("vencimiento_anios", 3) or 3),
                "spread_bps": float(row.get("spread_bps", 0) or 0),
                "callable": str(row.get("callable","")).upper() in ("TRUE","1","SI","YES","Y"),
                "precio_call": float(row.get("precio_call", np.nan)) if not pd.isna(row.get("precio_call", np.nan)) else None,
                "descripcion": str(row.get("descripcion",""))
            })
        elif t in ("MARKET","IDIOS"):
            events.append({
                "round": int(row.get("round", 1) or 1),
                "tipo": t,
                "bond_id": (str(row.get("bond_id")) if t=="IDIOS" else None),
                "delta_tasa_bps": float(row.get("delta_tasa_bps", 0) or 0),
                "impacto_bps": float(row.get("impacto_bps", 0) or 0),
                "descripcion": str(row.get("descripcion","")),
                "publicado": False
            })
    state["bonds"] = bonds
    state["events"] = events

# -------------------------------
# UI — COMPONENTES
# -------------------------------
def number_card(label, value, help_text=None):
    st.metric(label, f"{value:,.2f}", help=help_text)

def table(df: pd.DataFrame, height=360):
    st.dataframe(df, use_container_width=True, height=height)

# -------------------------------
# UI — MODERATOR
# -------------------------------
def ui_moderator(state: dict):
    g = state["game"]
    st.subheader("Panel del Moderador")
    # Parámetros del juego
    col1, col2, col3 = st.columns(3)
    with col1:
        g["rondas_totales"] = st.number_input("Rondas totales", 1, 20, int(g["rondas_totales"]), 1)
        g["fraccion_anio"] = st.number_input("Fracción de año por ronda", 0.05, 1.0, float(g["fraccion_anio"]), 0.05)
    with col2:
        g["bid_bp"] = st.number_input("Bid spread (bps)", 0, 500, int(g["bid_bp"]), 1)
        g["ask_bp"] = st.number_input("Ask spread (bps)", 0, 500, int(g["ask_bp"]), 1)
    with col3:
        g["comision_bps"] = st.number_input("Comisión por orden (bps)", 0, 200, int(g["comision_bps"]), 1)
        g["cash_inicial"] = st.number_input("Cash inicial por equipo", 1_000.0, 100_000_000.0, float(g["cash_inicial"]), 1_000.0, format="%.2f")

    st.markdown("### 1) Cargar escenario (CSV único)")
    up = st.file_uploader("Sube tu CSV de escenario (o usa el ejemplo)", type=["csv"])
    example_btn = st.button("Usar escenario de ejemplo")
    if up is not None:
        df = load_scenario_df(up)
        apply_scenario_to_state(df, state)
        st.success(f"Escenario cargado: {len(state['bonds'])} bonos y {len(state['events'])} eventos.")
        st.dataframe(df.head(20), use_container_width=True)
        save_state(state)
    elif example_btn:
        # escenario de ejemplo mínimo (3 bonos y 3 eventos)
        df = pd.DataFrame([
            # Bonos
            {"type":"BOND","bond_id":"B1","nombre":"Bono Tesoro 2028","valor_nominal":1000,"tasa_cupon_anual":0.08,"frecuencia_anual":2,"vencimiento_anios":3.0,"spread_bps":50,"callable":"FALSE","precio_call":"","descripcion":"Soberano"},
            {"type":"BOND","bond_id":"B2","nombre":"Corp Alfa 2030","valor_nominal":1000,"tasa_cupon_anual":0.09,"frecuencia_anual":2,"vencimiento_anios":4.0,"spread_bps":150,"callable":"TRUE","precio_call":1020,"descripcion":"Corporativo AAA"},
            {"type":"BOND","bond_id":"B3","nombre":"Corp Beta 2027","valor_nominal":1000,"tasa_cupon_anual":0.07,"frecuencia_anual":4,"vencimiento_anios":2.0,"spread_bps":220,"callable":"FALSE","precio_call":"","descripcion":"Corporativo BB"},
            # Eventos por ronda (se puede sobreescribir con el wizard)
            {"type":"MARKET","round":1,"delta_tasa_bps":75,"descripcion":"Shock de tasas +75 bps"},
            {"type":"MARKET","round":2,"delta_tasa_bps":-40,"descripcion":"Mejora macro -40 bps"},
            {"type":"IDIOS","round":3,"bond_id":"B3","impacto_bps":120,"descripcion":"Riesgo crédito B3 +120 bps"}
        ], columns=BOND_COLS)
        apply_scenario_to_state(df, state)
        st.success(f"Escenario de ejemplo cargado: {len(state['bonds'])} bonos y {len(state['events'])} eventos.")
        save_state(state)

    # Wizard de 3 eventos adaptativos (si faltan)
    st.markdown("### 2) Eventos adaptativos")
    if st.button("Generar/Actualizar 3 eventos adaptativos por defecto"):
        ensure_events_from_wizard(state)
        st.info("Se configuraron 3 eventos adaptativos (puedes editarlos exportando/importando el CSV de escenario).")
        save_state(state)

    # Publicar precios de la ronda actual
    st.markdown("### 3) Ronda actual")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.write(f"**Ronda actual:** {g['ronda_actual']} / {g['rondas_totales']}")
    with c2:
        st.write(f"**Estado:** {g['estado']}")
    with c3:
        if st.button("Publicar precios de ronda"):
            if not state["bonds"]:
                st.error("Primero carga un escenario con bonos.")
            else:
                publish_prices_for_round(state)
                save_state(state)
                st.success("Precios publicados y TRADING_ON habilitado.")
    with c4:
        if st.button("Cerrar TRADING (TRADING_OFF)"):
            g["estado"] = "TRADING_OFF"
            save_state(state)
            st.warning("Trading cerrado.")

    # Avanzar de ronda o finalizar
    if g["estado"] == "TRADING_OFF":
        if g["ronda_actual"] < g["rondas_totales"]:
            if st.button("Avanzar a la siguiente ronda ➡️"):
                g["ronda_actual"] += 1
                g["estado"] = "LOBBY"
                save_state(state)
                st.success(f"Avanzaste a la ronda {g['ronda_actual']}.")
        else:
            if st.button("Finalizar juego (FIN) 🏁"):
                g["estado"] = "FIN"
                save_state(state)
                st.success("Juego finalizado. Puedes exportar resultados.")

    st.markdown("### 4) Vistas")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Bonos","Eventos","Precios","Órdenes","Leaderboard"])
    with tab1:
        st.dataframe(pd.DataFrame(state["bonds"]), use_container_width=True)
    with tab2:
        st.dataframe(pd.DataFrame(state["events"]).sort_values(["round","tipo"]), use_container_width=True)
    with tab3:
        st.dataframe(pd.DataFrame(state["prices"]).sort_values(["ronda","bond_id"]), use_container_width=True)
    with tab4:
        st.dataframe(pd.DataFrame(state["orders"]), use_container_width=True)
    with tab5:
        st.dataframe(compute_leaderboard(state), use_container_width=True)

# -------------------------------
# UI — PARTICIPANTE
# -------------------------------
def ui_participant(state: dict):
    st.subheader("Panel del Participante")
    g = state["game"]
    st.caption(f"Ronda {g['ronda_actual']} — Estado: {g['estado']}")

    # Registro / login
    with st.form("reg_form", clear_on_submit=False):
        team_name = st.text_input("Nombre del equipo", "")
        pin = st.text_input("PIN (opcional)", type="password")
        submitted = st.form_submit_button("Registrar/Ingresar")
    if submitted and team_name.strip():
        t = team_get(state, team_name)
        if t is None:
            ok, msg = team_register(state, team_name.strip(), pin.strip())
            st.success(msg if ok else "No se pudo registrar")
            save_state(state)
        else:
            if t.get("pin","") and t.get("pin","") != pin:
                st.error("PIN incorrecto.")
            else:
                st.success(f"Bienvenido, {team_name}!")

    # Si no hay equipo seleccionado, mostrar leaderboard y salir
    team_current = st.session_state.get("team_current")
    if submitted and team_name.strip() and (team_get(state, team_name) is not None) and (not team_get(state, team_name).get("pin") or team_get(state, team_name).get("pin")==pin):
        st.session_state["team_current"] = team_name
        team_current = team_name

    if not team_current:
        st.info("Regístrate o ingresa tu equipo para continuar.")
        st.markdown("#### Leaderboard (vista pública)")
        st.dataframe(compute_leaderboard(state), use_container_width=True)
        return

    st.success(f"Equipo activo: **{team_current}**")
    pos, cash = team_positions_and_cash(state, team_current)
    colA, colB = st.columns(2)
    with colA:
        number_card("Cash disponible", cash)
    with colB:
        valor_pos = 0.0
        prices_mid = get_prices_dict(state, int(g["ronda_actual"]))
        for b, q in pos.items():
            valor_pos += q * prices_mid.get(b, 0.0)
        number_card("Valor de posiciones (mid)", valor_pos)
    st.markdown("#### Posiciones")
    df_pos = pd.DataFrame([{"Bono": b, "Cantidad": q} for b, q in pos.items()]).sort_values("Bono") if pos else pd.DataFrame(columns=["Bono","Cantidad"])
    st.dataframe(df_pos, use_container_width=True)

    st.markdown("#### Precios publicados (ronda actual)")
    df_prices = pd.DataFrame([p for p in state["prices"] if p["ronda"] == g["ronda_actual"]]).sort_values("bond_id")
    st.dataframe(df_prices, use_container_width=True)

    # Ordenes (sólo cuando TRADING_ON)
    st.markdown("#### Órdenes")
    if g["estado"] != "TRADING_ON":
        st.warning("El trading no está habilitado en este momento.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            side = st.selectbox("Side", ["BUY","SELL"])
        with c2:
            bond_id = st.selectbox("Bono", [b["bond_id"] for b in state["bonds"]])
        with c3:
            qty = st.number_input("Cantidad (enteros)", min_value=1, value=1, step=1)
        with c4:
            st.write(" ")
            if st.button("Enviar orden"):
                ok, msg = exec_order(state, team_current, side, str(bond_id), int(qty))
                if ok:
                    st.success(msg)
                    save_state(state)
                else:
                    st.error(msg)

    st.markdown("#### Leaderboard (en vivo)")
    st.dataframe(compute_leaderboard(state), use_container_width=True)

# -------------------------------
# RENDER PRINCIPAL
# -------------------------------
def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)

    # Selector de partida y rol
    with st.sidebar:
        st.header("Configuración")
        game_code = st.text_input("Game code (identificador de partida)", "MB-001")
        role = st.radio("Rol", ["Participante", "Moderador"])
        st.caption("Cada partida se guarda en un archivo local dentro de la carpeta 'games/'.")

    if not game_code.strip():
        st.stop()

    state = load_state(game_code.strip())

    if role == "Moderador":
        ui_moderator(state)
    else:
        ui_participant(state)

    # Auto-refresh ligero (opcional)
    st.sidebar.markdown("---")
    if st.sidebar.checkbox("Auto-actualizar cada 3 s (UI)", value=False):
        time.sleep(3)
        st.rerun()

if __name__ == "__main__":
    main()