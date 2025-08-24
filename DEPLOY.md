# Despliegue en Streamlit Cloud (paso a paso)

1. **Crea un repositorio en GitHub** (p.ej. `mision-bonos`).
2. Sube estos **4 archivos**:
   - `app.py`
   - `requirements.txt`
   - `README.md`
   - `.gitignore`
3. Entra a https://share.streamlit.io → **New app** → elige tu repo → `app.py`.
4. En **Advanced settings** deja el **branch** que uses (ej. `main`) y confirma.
5. Cuando cargue la app:
   - En la **barra lateral** elige un `Game code` (ej. `MB-001`) y el **Rol**.
   - Como **Moderador**: sube tu **CSV** de escenario o usa el **ejemplo** desde la UI.
   - Pulsa **Publicar precios de ronda** → queda **TRADING_ON**.
   - Los equipos se registran y operan en paralelo.
6. Si alguna vez queda “**Your app is in the oven**”:
   - En **Manage app → Clear cache** y **Reboot**.
   - Verifica que tu `requirements.txt` tenga solo:
     ```
     streamlit==1.37.1
     pandas==2.2.2
     numpy==1.26.4
     ```
   - Confirma que tu repo no contiene archivos pesados (la app permite subir CSV desde la UI).
