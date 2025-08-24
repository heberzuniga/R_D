# Misión Bonos — Simulador de Carteras (MVP)

Aplicación **Streamlit** lista para usar con estudiantes que competirán por la **mejor rentabilidad**.

## ¿Qué hace?
- Permite al **Moderador** crear una partida, cargar un **CSV de escenario** (bonos + eventos) o usar uno de ejemplo.
- Publica **tres eventos consecutivos** (propuestos por defecto y adaptables) que afectan el **valor de mercado** de los bonos:
  1. **Shock de tasas** `+75 bps` (MARKET)
  2. **Mejora macro** `-40 bps` (MARKET)
  3. **Riesgo crédito idiosincrático** `+120 bps` (IDIOS) sobre el bono con mayor *spread*
- Abre y cierra la **ventana de trading** por ronda.
- Los **equipos** se registran, **compran/venden** y su **rentabilidad** queda registrada automáticamente.
- **Leaderboard** en vivo y **resultado final** ordenado de **mayor a menor** rentabilidad.

## Estructura rápida
- `app.py` — app Streamlit (una sola página, con rol Moderador/Participante)
- `requirements.txt` — dependencias mínimas
- `games/` — carpeta que la app crea para guardar el estado por cada `game_code`

## Cómo ejecutar localmente
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Publicar en Streamlit Community Cloud
1. Crea un repositorio en GitHub y sube `app.py` y `requirements.txt`.
2. Desde https://share.streamlit.io despliega seleccionando tu repo y el archivo `app.py`.
3. (Opcional) Agrega tu CSV de escenario en la UI del Moderador o usa el ejemplo.

## Formato del CSV de escenario (una sola hoja)
Columnas esperadas (las que no uses pueden dejarse vacías):
```
type,bond_id,nombre,valor_nominal,tasa_cupon_anual,frecuencia_anual,vencimiento_anios,spread_bps,callable,precio_call,round,delta_tasa_bps,impacto_bps,descripcion
```
- Filas `BOND` definen bonos.
- Filas `MARKET` (campo `round` + `delta_tasa_bps`) definen shocks de mercado por ronda.
- Filas `IDIOS` (campo `round` + `bond_id` + `impacto_bps`) definen shocks idiosincráticos por bono y ronda.

> Si no subes un CSV, el Moderador puede cargar **un escenario de ejemplo** con 3 bonos y 3 eventos.

## Notas
- Persistencia simple mediante archivos JSON en `games/`. Esto permite que **varios equipos** participen en la misma partida (`game_code`) mientras corre la app.
- El modelo de precios usa **DCF** con YTM compuesto por `spread + evento de mercado + evento idiosincrático` (en **bps**).
- Comisiones y *bid/ask* configurables desde el panel del Moderador.