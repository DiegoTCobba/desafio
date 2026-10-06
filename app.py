"""CommunityLab · Interfaz Streamlit
Ingesta → Salud de la comunidad → Curaduría/aprobación → Paquete en OCI Object Storage.

Ejecutar:  streamlit run app.py
"""
import io
import json
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core import pipeline as pl
from core import prompts
from core.oci_storage import AlmacenLocal, AlmacenOCI

BASE = Path(__file__).parent
EJEMPLO = BASE / "data" / "interacciones_semana04.json"
COLUMNAS = ["autor", "canal", "tipo", "texto"]
TIPOS_ENTRADA = ["testimonio", "entrega_proyecto", "pregunta_tecnica", "feedback", "debate", "otro"]
COLOR_SENT = {"Altamente Positivo": "#1a9850", "Positivo": "#91cf60", "Neutral": "#b8b8b8",
              "Negativo": "#fc8d59", "Altamente Negativo": "#d73027"}
ICONO_ESTADO = {"pendiente": "🕓 Pendiente", "aprobado": "✅ Aprobado", "rechazado": "⛔ Rechazado"}

st.set_page_config(page_title="CommunityLab", page_icon="🚀", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.6rem;}
.hero {padding: 1.1rem 1.4rem; border-radius: 14px; margin-bottom: .8rem;
       background: linear-gradient(120deg, #C74634 0%, #7a2a8c 100%); color: #fff;}
.hero h1 {color:#fff; margin:0; font-size:1.9rem;}
.hero p {margin:.25rem 0 0; opacity:.92;}
.chip {display:inline-block; padding:2px 10px; border-radius:999px; font-size:.78rem; font-weight:600;
       margin-right:6px; background:rgba(199,70,52,.12); color:#C74634;}
.muted {color:#8a8a8a; font-size:.85rem;}
[data-testid="stMetricValue"] {font-size: 1.9rem;}
.preview {border:1px solid rgba(128,128,128,.25); border-radius:12px; padding:14px 16px; white-space:pre-wrap;}
</style>
""", unsafe_allow_html=True)


# ============================================================ estado
def init_state():
    defaults = {"df": None, "df_ver": 0, "origen": "Discord_Grupo_ONE_G10", "periodo": "Semana_04",
                "resultado": None, "activos": [], "almacen": None, "guardado": None, "msg_ingesta": None,
                "listado": None}
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def _set_lote(origen, periodo, interacciones, msg):
    items = pl.normalizar_interacciones(interacciones)
    if not items:
        st.session_state.msg_ingesta = ("error", "No se encontraron interacciones con texto.")
        return
    st.session_state.df = pd.DataFrame(items)[COLUMNAS]
    st.session_state.df_ver += 1
    if origen:
        st.session_state.origen = origen
    if periodo:
        st.session_state.periodo = periodo
    st.session_state.msg_ingesta = ("success", f"{msg}: {len(items)} interacciones cargadas.")


def cargar_ejemplo():
    o, p, it = pl.leer_lote(json.loads(EJEMPLO.read_text(encoding="utf-8")))
    _set_lote(o, p, it, "Lote de ejemplo")


def cargar_archivo(archivo):
    if archivo is None:
        st.session_state.msg_ingesta = ("warning", "Primero selecciona un archivo.")
        return
    try:
        crudo = archivo.getvalue()
        if archivo.name.lower().endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(crudo))
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(crudo), encoding="latin-1")
            df.columns = [c.strip().lower() for c in df.columns]
            _set_lote(None, None, df.to_dict("records"), f"CSV {archivo.name}")
        else:
            o, p, it = pl.leer_lote(json.loads(crudo.decode("utf-8")))
            _set_lote(o, p, it, f"JSON {archivo.name}")
    except Exception as e:  # noqa: BLE001
        st.session_state.msg_ingesta = ("error", f"No se pudo leer el archivo: {e}")


def cargar_pegado():
    try:
        o, p, it = pl.leer_lote(json.loads(st.session_state.get("json_pegado", "")))
        _set_lote(o, p, it, "JSON pegado")
    except Exception as e:  # noqa: BLE001
        st.session_state.msg_ingesta = ("error", f"JSON inválido: {e}")


def _limpiar_widgets_activos():
    for k in [k for k in st.session_state if str(k).startswith(("txt_", "tit_"))]:
        del st.session_state[k]


def buscar(aid):
    return next(a for a in st.session_state.activos if a["id"] == aid)


def set_estado(aid, estado):
    buscar(aid)["estado"] = estado


def restablecer(aid):
    a = buscar(aid)
    a["contenido"], a["titulo"], a["estado"] = a["original"], a["titulo_original"], "pendiente"
    st.session_state.pop(f"txt_{aid}", None)
    st.session_state.pop(f"tit_{aid}", None)


def aprobar_pendientes():
    for a in st.session_state.activos:
        if a["estado"] == "pendiente":
            a["estado"] = "aprobado"


def reiniciar_curaduria():
    for a in st.session_state.activos:
        a["estado"] = "pendiente"


init_state()

# ============================================================ barra lateral
with st.sidebar:
    st.markdown("### 🚀 CommunityLab")
    st.caption("Motor inteligente de transformación y distribución · Hackathon ONE G10")

    st.subheader("🧠 Motor de IA")
    hay_key = bool(os.getenv("GOOGLE_API_KEY"))
    modo_lbl = st.radio("Modo", ["Gemini (LangChain)", "Demo sin API"], index=0 if hay_key else 1,
                        help="El modo demo usa heurísticas y plantillas: sirve para probar la interfaz sin gastar cuota.")
    modo = "gemini" if modo_lbl.startswith("Gemini") else "demo"
    api_key = st.text_input("GOOGLE_API_KEY", value=os.getenv("GOOGLE_API_KEY", ""), type="password",
                            disabled=modo == "demo")
    modelo = st.text_input("Modelo", value=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"), disabled=modo == "demo")
    temperatura = st.slider("Creatividad (temperature)", 0.0, 1.0, 0.7, 0.05, disabled=modo == "demo")

    with st.expander("🎯 Voz de marca y reglas de ruteo"):
        voz = st.text_area("Voz de marca", value=prompts.VOZ_MARCA_DEFAULT, height=160)
        umbral = st.slider("Sentimiento mínimo para Caso de Éxito", 0.0, 1.0, 0.4, 0.05,
                           help="Testimonios/proyectos por encima de este puntaje se convierten en casos de éxito.")
        max_por_ruta = st.number_input("Máx. interacciones a transformar por ruta", 1, 10, 3)

    st.subheader("☁️ OCI Object Storage")
    bucket = st.text_input("Bucket", value=os.getenv("OCI_BUCKET", "communitylab-activos-marketing"))
    perfil = st.text_input("Perfil de ~/.oci/config", value=os.getenv("OCI_PROFILE", "DEFAULT"))
    crear_bucket = st.checkbox("Crear bucket si no existe")
    if st.button("🔌 Conectar a OCI", width="stretch"):
        with st.spinner("Conectando…"):
            st.session_state.almacen = AlmacenOCI(bucket, perfil, crear_bucket=crear_bucket)
    alm = st.session_state.almacen
    if alm is None:
        st.info("Sin conexión: los paquetes se guardarán en la carpeta local `salida_local/`.")
    elif alm.disponible:
        st.success(alm.detalle)
    else:
        st.error(alm.detalle)
        st.caption("Se usará el respaldo local hasta que la conexión funcione.")


def almacen_activo():
    a = st.session_state.almacen
    if a is not None and a.disponible and a.bucket == bucket:
        return a
    return AlmacenLocal(bucket, BASE / "salida_local")


# ============================================================ encabezado
st.markdown("""<div class="hero"><h1>🚀 CommunityLab</h1>
<p>Convierte la actividad orgánica de tu comunidad en posts, casos de éxito, FAQs y resúmenes semanales listos para publicar.</p></div>""",
            unsafe_allow_html=True)

res = st.session_state.resultado
activos = st.session_state.activos
n_aprob = sum(a["estado"] == "aprobado" for a in activos)
tab_in, tab_salud, tab_cur, tab_pkg = st.tabs([
    "📥 1 · Ingesta", "📊 2 · Salud de la comunidad",
    "✍️ 3 · Curaduría",  # etiqueta fija: si cambia, Streamlit vuelve a la primera pestaña
    "☁️ 4 · Paquete & OCI",
])

# ============================================================ 1 · ingesta
with tab_in:
    c1, c2 = st.columns([2, 1], gap="large")
    with c1:
        fuente = st.radio("Fuente de datos", ["Lote de ejemplo", "Subir JSON / CSV", "Pegar JSON"], horizontal=True)
        if fuente == "Lote de ejemplo":
            st.caption("9 mensajes simulados de un Discord de la comunidad ONE (logros, dudas, proyectos, feedback).")
            st.button("📂 Cargar lote de ejemplo", on_click=cargar_ejemplo)
        elif fuente == "Subir JSON / CSV":
            archivo = st.file_uploader("Archivo", type=["json", "csv"],
                                       help="JSON con el formato del reto o CSV con columnas autor, canal, tipo, texto.")
            st.button("📂 Cargar archivo", on_click=cargar_archivo, args=(archivo,))
        else:
            st.text_area("Payload JSON", key="json_pegado", height=180,
                         placeholder='{"origen_comunidad": "...", "periodo_referencia": "...", "interacciones": [...]}')
            st.button("📂 Cargar JSON", on_click=cargar_pegado)
    with c2:
        st.text_input("Origen de la comunidad", key="origen")
        st.text_input("Período de referencia", key="periodo")

    if st.session_state.msg_ingesta:
        nivel, texto = st.session_state.msg_ingesta
        getattr(st, nivel)(texto)

    editado = None
    if st.session_state.df is not None:
        st.markdown("#### Interacciones del lote")
        st.caption("Puedes editar, agregar o eliminar filas antes de procesar.")
        editado = st.data_editor(
            st.session_state.df, num_rows="dynamic", width="stretch", hide_index=True,
            key=f"editor_{st.session_state.df_ver}",
            column_config={
                "autor": st.column_config.TextColumn("Autor", width="small"),
                "canal": st.column_config.TextColumn("Canal", width="small"),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=TIPOS_ENTRADA, width="small"),
                "texto": st.column_config.TextColumn("Mensaje", width="large"),
            })
    else:
        st.info("Carga un lote para empezar.")

    procesar = st.button("⚡ Procesar lote y generar activos", type="primary",
                         disabled=editado is None or editado.empty)
    if procesar:
        payload = {"origen_comunidad": st.session_state.origen, "periodo_referencia": st.session_state.periodo,
                   "interacciones": editado.to_dict("records")}
        try:
            motor = pl.MotorCommunityLab(modo=modo, api_key=api_key, modelo=modelo, temperatura=temperatura,
                                         voz_marca=voz, umbral_exito=umbral, max_por_ruta=max_por_ruta)
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo iniciar el motor: {e}")
            st.stop()
        with st.status("Procesando lote…", expanded=True) as estado:
            try:
                resultado = motor.procesar(payload, progreso=estado.write)
            except Exception as e:  # noqa: BLE001
                estado.update(label="Error al procesar", state="error")
                st.error(str(e))
                st.stop()
            estado.update(label=f"Listo: {resultado['resumen']['total_interacciones_procesadas']} interacciones → "
                                f"{len(resultado['activos'])} activos generados", state="complete", expanded=False)
        _limpiar_widgets_activos()
        st.session_state.resultado = resultado
        st.session_state.activos = resultado["activos"]
        st.session_state.guardado = None
        st.session_state.listado = None
        st.rerun()

    if res:
        for aviso in res.get("avisos", []):
            st.warning(aviso)
        st.success(f"Último procesamiento: {res['generado_en']} · motor {res['motor']['modelo']} · "
                   f"{len(activos)} activos. Revisa las pestañas 2, 3 y 4.")

# ============================================================ 2 · salud
with tab_salud:
    if not res:
        st.info("Procesa un lote en la pestaña **Ingesta** para ver el tablero.")
    else:
        r = res["resumen"]
        m1, m2, m3, m4 = st.columns([1, 1.8, 1, 1])
        m1.metric("Interacciones", r["total_interacciones_procesadas"])
        m2.metric("Sentimiento predominante", r["sentimiento_predominante"])
        m3.metric("Puntaje promedio", f"{r['puntaje_sentimiento_promedio']:+.2f}", help="-1 muy negativo · +1 muy positivo")
        m4.metric("Alertas de apoyo", len(r["alertas_apoyo"]))
        if r.get("lectura_salud"):
            st.info(f"🩺 {r['lectura_salud']}")

        df_an = pd.DataFrame(res["analisis"])
        df_an["ruta_lbl"] = df_an["ruta"].map(pl.RUTAS)
        df_an["categoria_lbl"] = df_an["categoria"].map(pl.CATEGORIAS)
        df_an["temas_txt"] = df_an["temas"].apply(", ".join)

        g1, g2 = st.columns(2, gap="large")
        with g1:
            st.markdown("##### Distribución de sentimiento")
            ds = pd.DataFrame([{"sentimiento": k, "n": v} for k, v in r["distribucion_sentimiento"].items()])
            st.altair_chart(alt.Chart(ds).mark_bar(cornerRadiusEnd=4).encode(
                x=alt.X("n:Q", title="Interacciones", axis=alt.Axis(tickMinStep=1)),
                y=alt.Y("sentimiento:N", sort=pl.ORDEN_SENTIMIENTO, title=None, axis=alt.Axis(labelLimit=200)),
                color=alt.Color("sentimiento:N", scale=alt.Scale(domain=list(COLOR_SENT), range=list(COLOR_SENT.values())),
                                legend=None),
                tooltip=["sentimiento", "n"]).properties(height=220), width="stretch")
        with g2:
            st.markdown("##### Temas en tendencia")
            dt = pd.DataFrame([{"tema": k, "n": v} for k, v in r["frecuencia_temas"].items()])
            st.altair_chart(alt.Chart(dt).mark_bar(cornerRadiusEnd=4, color="#7a2a8c").encode(
                x=alt.X("n:Q", title="Menciones", axis=alt.Axis(tickMinStep=1)),
                y=alt.Y("tema:N", sort="-x", title=None, axis=alt.Axis(labelLimit=200)),
                tooltip=["tema", "n"]).properties(height=max(220, 28 * len(dt))),
                width="stretch")

        g3, g4 = st.columns([3, 2], gap="large")
        with g3:
            st.markdown("##### Mapa de momentos (sentimiento × relevancia)")
            st.altair_chart(alt.Chart(df_an).mark_circle(size=220, opacity=.85).encode(
                x=alt.X("sentimiento_puntaje:Q", title="Sentimiento", scale=alt.Scale(domain=[-1, 1])),
                y=alt.Y("puntaje_relevancia:Q", title="Relevancia", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color("ruta_lbl:N", title="Ruta"),
                tooltip=["autor", "canal", "ruta_lbl", "puntaje_relevancia", "sentimiento", "texto"]
            ).properties(height=280), width="stretch")
        with g4:
            st.markdown("##### Ruteo del flujo")
            dr = pd.DataFrame([{"ruta": k, "n": v} for k, v in r["distribucion_rutas"].items()])
            st.altair_chart(alt.Chart(dr).mark_arc(innerRadius=55).encode(
                theta="n:Q", color=alt.Color("ruta:N", title=None, legend=alt.Legend(orient="bottom", columns=2)),
                tooltip=["ruta", "n"]).properties(height=280), width="stretch")

        st.markdown("##### Ranking de interacciones")
        st.dataframe(
            df_an[["puntaje_relevancia", "autor", "canal", "categoria_lbl", "sentimiento", "sentimiento_puntaje",
                   "ruta_lbl", "temas_txt", "cita_destacada", "justificacion"]],
            hide_index=True, width="stretch",
            column_config={
                "puntaje_relevancia": st.column_config.ProgressColumn("Relevancia", min_value=0, max_value=100, format="%d"),
                "autor": "Autor", "canal": "Canal", "categoria_lbl": "Categoría", "sentimiento": "Sentimiento",
                "sentimiento_puntaje": st.column_config.NumberColumn("Puntaje", format="%+.2f"),
                "ruta_lbl": "Ruta", "temas_txt": "Temas", "cita_destacada": "Cita destacada",
                "justificacion": "Justificación"})

        if r["alertas_apoyo"]:
            st.markdown("##### 🆘 Miembros que necesitan apoyo")
            for al in r["alertas_apoyo"]:
                st.error(f"**{al['autor']}** en `{al['canal']}` · {al['sentimiento']}\n\n> {al['texto']}")

# ============================================================ 3 · curaduría
with tab_cur:
    if not activos:
        st.info("Aún no hay activos generados.")
    else:
        f1, f2, f3, f4 = st.columns([3, 2, 1.2, 1.2])
        tipos_sel = f1.multiselect("Tipo de activo", list(pl.TIPOS_ACTIVO), default=list(pl.TIPOS_ACTIVO),
                                   format_func=pl.TIPOS_ACTIVO.get)
        estado_sel = f2.selectbox("Estado", ["Todos", "pendiente", "aprobado", "rechazado"],
                                  format_func=lambda x: ICONO_ESTADO.get(x, x))
        f3.button("✅ Aprobar pendientes", on_click=aprobar_pendientes, width="stretch")
        f4.button("↺ Reiniciar", on_click=reiniciar_curaduria, width="stretch")

        visibles = [a for a in activos if a["tipo"] in tipos_sel and (estado_sel == "Todos" or a["estado"] == estado_sel)]
        st.progress(n_aprob / len(activos), text=f"{n_aprob} de {len(activos)} activos aprobados")
        st.caption(f"Mostrando {len(visibles)} de {len(activos)} activos · edita el texto directamente; los cambios se guardan al salir del campo.")

        for a in visibles:
            with st.container(border=True):
                h1, h2 = st.columns([5, 1])
                h1.markdown(f"<span class='chip'>{pl.TIPOS_ACTIVO[a['tipo']]}</span>"
                            f"<span class='muted'>Origen: {a['origen']}</span>", unsafe_allow_html=True)
                h2.markdown(f"**{ICONO_ESTADO[a['estado']]}**")

                a["titulo"] = st.text_input("Título", value=a["titulo"], key=f"tit_{a['id']}")
                alto = 120 if a["tipo"] == "post_x" else 240
                a["contenido"] = st.text_area("Contenido", value=a["contenido"], key=f"txt_{a['id']}", height=alto)

                info = []
                if a["tipo"] == "post_x":
                    n = len(a["contenido"])
                    info.append(f"{'🔴' if n > 280 else '🟢'} {n}/280 caracteres")
                elif a["tipo"] == "post_linkedin":
                    info.append(f"{len(a['contenido'])} caracteres · engagement estimado: "
                                f"{a['meta'].get('potencial_engagement', '—')}")
                elif a["tipo"] == "faq":
                    info.append(f"Nivel: {a['meta'].get('nivel', '—')} · status: {a['meta'].get('status', '—')}")
                elif a["tipo"] == "newsletter":
                    info.append(f"Sección: {a['meta'].get('seccion', '—')}")
                if a["contenido"] != a["original"] or a["titulo"] != a["titulo_original"]:
                    info.append("✏️ editado")
                st.caption(" · ".join(info))

                b1, b2, b3, b4 = st.columns([1, 1, 1, 3])
                b1.button("✅ Aprobar", key=f"ap_{a['id']}", on_click=set_estado, args=(a["id"], "aprobado"),
                          disabled=a["estado"] == "aprobado", width="stretch")
                b2.button("⛔ Rechazar", key=f"re_{a['id']}", on_click=set_estado, args=(a["id"], "rechazado"),
                          disabled=a["estado"] == "rechazado", width="stretch")
                b3.button("↩️ Restablecer", key=f"rs_{a['id']}", on_click=restablecer, args=(a["id"],),
                          width="stretch")
                with b4.popover("👁️ Vista previa", width="stretch"):
                    if a["tipo"] in ("post_linkedin", "post_x"):
                        st.markdown(f"**{st.session_state.origen}** · {a['meta'].get('canal_recomendado', '')}")
                        st.markdown(f"<div class='preview'>{a['contenido']}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"### {a['titulo']}")
                        st.markdown(a["contenido"])

# ============================================================ 4 · paquete & OCI
with tab_pkg:
    if not res:
        st.info("Procesa un lote y aprueba activos para armar el paquete de distribución.")
    else:
        incluir = st.toggle("Incluir activos pendientes (no aprobados aún)", value=False)
        paquete = pl.construir_paquete(res, activos, incluir)
        cur = paquete["curaduria"]
        n_pkg = sum(len(v) for v in paquete["activos_distribucion_generados"].values())
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Activos en el paquete", n_pkg)
        k2.metric("Aprobados", cur["aprobados"])
        k3.metric("Pendientes", cur["pendientes"])
        k4.metric("Rechazados", cur["rechazados"])

        p1, p2 = st.columns([3, 2], gap="large")
        with p1:
            st.markdown("##### Vista del paquete")
            vista = st.session_state.guardado["paquete"] if st.session_state.guardado else paquete
            st.json(vista, expanded=1)
            d1, d2 = st.columns(2)
            nombre = f"paquete-{pl.slug(res['periodo_referencia'])}"
            d1.download_button("⬇️ Descargar JSON", json.dumps(vista, ensure_ascii=False, indent=2),
                               f"{nombre}.json", "application/json", width="stretch")
            d2.download_button("⬇️ Descargar informe (.md)", pl.informe_markdown(vista), f"{nombre}.md",
                               "text/markdown", width="stretch")
        with p2:
            destino = almacen_activo()
            st.markdown("##### Persistencia")
            if destino.tipo == "oci":
                st.success(f"Destino: bucket **{destino.bucket}** en OCI Object Storage")
            else:
                st.warning(f"Destino: respaldo local (`salida_local/{destino.bucket}`). "
                           "Conecta OCI en la barra lateral para cumplir el requisito del MVP.")
            if n_pkg == 0:
                st.caption("Aprueba al menos un activo en **Curaduría** (o incluye los pendientes).")
            if st.button("☁️ Guardar paquete", type="primary", disabled=n_pkg == 0, width="stretch"):
                with st.spinner("Subiendo objetos…"):
                    st.session_state.guardado = pl.guardar_paquete(destino, paquete, res)
                st.session_state.listado = None
                st.rerun()

            g = st.session_state.guardado
            if g:
                (st.success if g["ok"] else st.error)(
                    "Paquete guardado con éxito" if g["ok"] else "Algunos objetos no se pudieron guardar")
                st.dataframe(pd.DataFrame(g["objetos"]), hide_index=True, width="stretch")

            st.markdown("##### Historial en el bucket")
            if st.button("🔄 Ver objetos guardados", width="stretch"):
                try:
                    st.session_state.listado = destino.listar()
                except Exception as e:  # noqa: BLE001
                    st.error(f"No se pudo listar: {e}")
            if st.session_state.listado is not None:
                if st.session_state.listado:
                    st.dataframe(pd.DataFrame(st.session_state.listado), hide_index=True, width="stretch")
                else:
                    st.caption("El bucket aún no tiene objetos bajo `activos/`.")
