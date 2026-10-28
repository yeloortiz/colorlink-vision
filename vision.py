import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from PIL import Image
import base64
import sqlalchemy
import pandas as pd
import os
import io

# ==========================================
# 0. INICIALIZACIÓN DE ESTADO DE SESIÓN
# ==========================================
if 'lectura_guardada' not in st.session_state:
    st.session_state.lectura_guardada = False

# ==========================================
# 1. CONFIGURACIÓN DEL LOGO E ICONO iOS
# ==========================================
logo_path = "apple-touch-icon.png"  # Asegúrate de que este archivo exista en tu repositorio
try:
    Colorlink_ONCLOUD_logo = Image.open(logo_path)
    with open(logo_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode()
    logo_base64 = f"data:image/png;base64,{encoded_string}"
except Exception:
    Colorlink_ONCLOUD_logo = None
    logo_base64 = ""

st.set_page_config(
    page_title="Colorlink Vision",
    page_icon=Colorlink_ONCLOUD_logo if Colorlink_ONCLOUD_logo else "🎨",
    layout="centered"
)

if logo_base64:
    st.markdown(
        f"""
        <head>
            <link rel="apple-touch-icon" href="{logo_base64}">
            <link rel="shortcut icon" href="{logo_base64}">
        </head>
        """,
        unsafe_allow_html=True
    )

if Colorlink_ONCLOUD_logo:
    st.image(Colorlink_ONCLOUD_logo, width=200)

st.title("Colorlink Vision")
st.caption("Extracción automática de deltas y coordenadas CIELAB con registro en Base de Datos.")

# ==========================================
# 2. CONEXIÓN A SUPABASE Y GEMINI API
# ==========================================
try:
    db_config = st.secrets['connections']['postgresql']
    db_url = f"postgresql+psycopg2://{db_config['username']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}"
    engine = sqlalchemy.create_engine(db_url)
except Exception as e:
    st.error(f"Error al configurar el motor de base de datos: {e}")
    st.stop()

api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    api_key = st.sidebar.text_input("Gemini API Key", type="password")

if not api_key:
    st.info("👈 Introduce tu Gemini API Key en el menú lateral o configúrala en los Secrets para comenzar.")
    st.stop()

# Forzamos la variable de entorno para que el cliente la reconozca sin confundirla con OAuth
os.environ["GEMINI_API_KEY"] = api_key

# Inicializamos el cliente pasando la clave directamente
client = genai.Client(api_key=api_key)

# ==========================================
# 3. ESQUEMA PYDANTIC PARA EXTRACCIÓN
# ==========================================
class DatosEspectro(BaseModel):
    equipo_software: str = Field(default="Desconocido", description="Modelo de equipo o software si aparece")
    muestra_id: str = Field(default="N/A", description="Número o identificador de muestra/lote si existe")
    
    patron_L: float = Field(default=0.0, description="L del patrón")
    patron_a: float = Field(default=0.0, description="a del patrón")
    patron_b: float = Field(default=0.0, description="b del patrón")
    
    medido_L: float = Field(default=0.0, description="L* medido")
    medido_a: float = Field(default=0.0, description="a* medido")
    medido_b: float = Field(default=0.0, description="b* medido")
    
    delta_L: float = Field(default=0.0, description="dL* / Delta L")
    delta_a: float = Field(default=0.0, description="da* / Delta a")
    delta_b: float = Field(default=0.0, description="db* / Delta b")
    
    delta_E: float = Field(default=0.0, description="dE*ab / Delta E total")
    veredicto: str = Field(default="PENDIENTE", description="Aprobación si existe: PASS, FAIL, etc.")
    comentario: str = Field(default="", description="Texto o comentario al pie del reporte")

# ==========================================
# 4. INICIALIZACIÓN DE SESSION STATE
# ==========================================
if 'dl_val' not in st.session_state: st.session_state['dl_val'] = 0.0
if 'da_val' not in st.session_state: st.session_state['da_val'] = 0.0
if 'db_val' not in st.session_state: st.session_state['db_val'] = 0.0
if 'ln_val' not in st.session_state: st.session_state['ln_val'] = 0.0
if 'an_val' not in st.session_state: st.session_state['an_val'] = 0.0
if 'bn_val' not in st.session_state: st.session_state['bn_val'] = 0.0

# ==========================================
# 5. SELECCIÓN EN CASCADA Y REGISTRO NUEVO
# ==========================================
st.subheader("1. Identificación de la Pieza (Jerarquía)")

oem_seleccionado = None
master_seleccionado = None
part_number_val = None
part_name_val = None
supplier_seleccionado = None

# Inicialización segura de DataFrames para evitar NameError
df_oems = pd.DataFrame()
df_masters = pd.DataFrame()
df_parts = pd.DataFrame()
df_suppliers = pd.DataFrame()

try:
    # --- NIVEL 1: OEM (Desde la tabla normalizada 'oems') ---
    df_oems = pd.read_sql("SELECT id, oem_name FROM oems ORDER BY oem_name;", engine)
    
    if not df_oems.empty:
        oem_dict = dict(zip(df_oems['oem_name'], df_oems['id']))
        lista_oems = list(oem_dict.keys())
        
        oem_choice = st.selectbox("OEM", lista_oems, key="oem_choice")
        oem_seleccionado = oem_dict[oem_choice]  # Guardamos el ID numérico del OEM

        if oem_seleccionado:
            
            # --- NIVEL 2: MASTER (Desde la tabla normalizada 'masters' filtrado por oem_id) ---
            query_masters = sqlalchemy.text("SELECT id, master_name FROM masters WHERE oem_id = :oem_id ORDER BY master_name;")
            df_masters = pd.read_sql(query_masters, engine, params={"oem_id": oem_seleccionado})

            if not df_masters.empty:
                master_dict = dict(zip(df_masters['master_name'], df_masters['id']))
                lista_masters = list(master_dict.keys())
                
                master_choice = st.selectbox("Master Name", lista_masters, key="master_choice")
                master_seleccionado = master_dict[master_choice]  # Guardamos el ID numérico del Master

                if master_seleccionado:
                    
                    # --- NIVEL 3: PARTE (Number y Name desde 'lecturas' filtrado por master_id) ---
                    query_parts = sqlalchemy.text("SELECT DISTINCT part_number, part_name FROM lecturas WHERE master_id = :m_id AND part_number IS NOT NULL;")
                    df_parts = pd.read_sql(query_parts, engine, params={"m_id": master_seleccionado})

                    lista_parts = []
                    if not df_parts.empty:
                        df_parts['display'] = df_parts['part_number'].astype(str) + " - " + df_parts['part_name'].fillna('')
                        lista_parts = df_parts['display'].tolist()
                    lista_parts.append("➕ Agregar nueva Parte...")

                    part_choice = st.selectbox("Part Number / Name", lista_parts)
                    if part_choice == "➕ Agregar nueva Parte...":
                        col_pn, col_pname = st.columns(2)
                        with col_pn:
                            part_number_val = st.text_input("Número de Parte:", key="part_number_val")
                        with col_pname:
                            part_name_val = st.text_input("Nombre de la Parte:", key="part_name_val")
                    else:
                        if " - " in part_choice:
                            part_number_val = part_choice.split(" - ")[0]
                            part_name_val = part_choice.split(" - ")[1]
                        else:
                            part_number_val = part_choice
                            part_name_val = ""

                    if part_number_val:
                        # --- NIVEL 4: SUPPLIER (Desde 'lecturas' usando master_id y part_number) ---
                        query_suppliers = sqlalchemy.text("SELECT DISTINCT supplier_name FROM lecturas WHERE master_id = :m_id AND part_number = :p_num AND supplier_name IS NOT NULL;")
                        df_suppliers = pd.read_sql(query_suppliers, engine, params={"m_id": master_seleccionado, "p_num": part_number_val})
                        
                        lista_suppliers = df_suppliers["supplier_name"].tolist() if not df_suppliers.empty else []
                        lista_suppliers.append("➕ Agregar nuevo Proveedor...")

                        supplier_choice = st.selectbox("Supplier Name", lista_suppliers)
                        if supplier_choice == "➕ Agregar nuevo Proveedor...":
                            supplier_seleccionado = st.text_input("Escribe el nombre del nuevo Proveedor:", key="supplier_seleccionado")
                        else:
                            supplier_seleccionado = supplier_choice   
            
            else:
                st.info("ℹ️ Este OEM aún no tiene Masters registrados en la base de datos.")
    else:
        st.warning("⚠️ No hay OEMs registrados en Supabase. Por favor da de alta al menos uno en el Table Editor.")

except Exception as e:
    st.warning(f"Nota: Los menús interactivos se están inicializando. ({e})")

st.markdown("---")

# ==========================================
# 6. CAPTURA Y ANÁLISIS DE IMAGEN CON GEMINI
# ==========================================
st.subheader("2. Captura o Carga la Lectura")

opcion_carga = st.radio("Selecciona origen de la imagen:", ["Subir Foto / Archivo / Screenshot", "Usar Cámara Directa"])
imagen_cargada = None

if opcion_carga == "Subir Foto / Archivo / Screenshot":
    archivo = st.file_uploader("Selecciona archivo o pega imagen", type=["jpg", "jpeg", "png"], key="archivo")
    if archivo:
        imagen_cargada = Image.open(archivo)
else:
    foto = st.camera_input("Toma una foto a la pantalla del espectrofotómetro")
    if foto:
        imagen_cargada = Image.open(foto)

if imagen_cargada:
    st.image(imagen_cargada, caption="Lectura seleccionada", use_column_width=True)
    
    if st.button("🚀 Extraer Datos con Gemini", type="primary", use_container_width=True):
        with st.spinner("Analizando reporte metrológico con Gemini..."):
            try:
                prompt = """
                Analiza cuidadosamente esta imagen de reporte o pantalla de espectrofotómetro.
                Extrae con precisión matemática absoluta todos los valores correspondientes a:
                - Patrón (L, a, b)
                - Medido (L*, a*, b*)
                - Desviación/Deltas (dL*, da*, db*, dE*ab)
                - Información de equipo, muestra, veredicto y comentarios.
                
                Asegúrate de conservar el signo numérico correcto (+/-) en los deltas. Si algún valor no está visible, usa 0.0.
                """
                
                response = client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=[imagen_cargada, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=DatosEspectro,
                        temperature=0.0
                    )
                )

                # Depuración: Ver qué respondió exactamente la IA si hay dudas
                # st.write("Respuesta cruda de Gemini:", response.text)
                
                datos = DatosEspectro.model_validate_json(response.text)
                
                # Guardamos de forma segura en st.session_state
                st.session_state['dl_val'] = float(datos.delta_L if datos.delta_L is not None else 0.0)
                st.session_state['da_val'] = float(datos.delta_a if datos.delta_a is not None else 0.0)
                st.session_state['db_val'] = float(datos.delta_b if datos.delta_b is not None else 0.0)
                st.session_state['ln_val'] = float(datos.medido_L if datos.medido_L is not None else 0.0)
                st.session_state['an_val'] = float(datos.medido_a if datos.medido_a is not None else 0.0)
                st.session_state['bn_val'] = float(datos.medido_b if datos.medido_b is not None else 0.0)

                st.success("¡Datos extraídos con éxito!")

                st.markdown("### 📊 Desviaciones (Deltas)")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("dL*", f"{st.session_state['dl_val']:.2f}")
                m2.metric("da*", f"{st.session_state['da_val']:.2f}")
                m3.metric("db*", f"{st.session_state['db_val']:.2f}")
                m4.metric("dE*ab", f"{datos.delta_E:.2f}")
                
                st.markdown("### 📑 Detalle Metrológico")
                tabla_comparativa = {
                    "Parámetro": ["L (Luminosidad)", "a (Verde-Rojo)", "b (Azul-Amarillo)"],
                    "Patrón / Master": [datos.patron_L, datos.patron_a, datos.patron_b],
                    "Muestra Medida": [datos.medido_L, datos.medido_a, datos.medido_b],
                    "Delta (Desviación)": [datos.delta_L, datos.delta_a, datos.delta_b]
                }
                st.dataframe(tabla_comparativa, use_container_width=True)
                st.info(f"**Veredicto:** {datos.veredicto} | **Muestra/Lote:** {datos.muestra_id}\n\n**Comentario:** {datos.comentario}")

            except Exception as e:
                st.error(f"Error al procesar la imagen con Gemini: {e}")

st.markdown("---")

# ==========================================
# 7. VALORES FINALES Y EVALUACIÓN VISUAL (-3 a 3)
# ==========================================
st.subheader("3. Confirmación de Valores y Evaluación Visual")

# Mostramos los valores de las desviaciones directamente (solo lectura para el usuario)
col_dl, col_da, col_db = st.columns(3)
with col_dl:
    st.metric("Delta L* (dL*)", f"{st.session_state['dl_val']:.2f}")
with col_da:
    st.metric("Delta a* (da*)", f"{st.session_state['da_val']:.2f}")
with col_db:
    st.metric("Delta b* (db*)", f"{st.session_state['db_val']:.2f}")

st.markdown("#### Evaluación Visual por Eje (-3 a 3)")
st.caption("0 = color exacto | ±1, ±2 = aprobado | ±3 = rechazado")

col_vl, col_va, col_vb = st.columns(3)
with col_vl:
    lv_val = st.selectbox("Eval Eje L (lv)", [3, 2, 1, 0, -1, -2, -3], index=3, key="lv_val")
with col_va:
    av_val = st.selectbox("Eval Eje a (av)", [3, 2, 1, 0, -1, -2, -3], index=3, key="av_val")
with col_vb:
    bv_val = st.selectbox("Eval Eje b (bv)", [3, 2, 1, 0, -1, -2, -3], index=3, key="bv_val")

st.markdown("---")

# ==========================================
# 8. BOTÓN DE GUARDADO EN SUPABASE
# ==========================================
st.markdown("---")

if st.button("💾 Guardar Lectura en la Nube", type="primary", use_container_width=True):
    
    # Recuperamos de forma segura desde session_state
    ln_val = st.session_state.get('ln_val', 0.0)
    an_val = st.session_state.get('an_val', 0.0)
    bn_val = st.session_state.get('bn_val', 0.0)

    lv_val = st.session_state.get('lv_val', 0)
    av_val = st.session_state.get('av_val', 0)
    bv_val = st.session_state.get('bv_val', 0)

    # Validaciones defensivas antes de impactar la base de datos
    if not master_seleccionado:
        st.warning("⚠️ Debes seleccionar un Master válido antes de guardar.")
    elif not part_number_val:
        st.warning("⚠️ El número de parte es obligatorio.")
    elif not supplier_seleccionado:
        st.warning("⚠️ Debes especificar el proveedor.")
    else:
        try:
            insert_query = sqlalchemy.text("""
                INSERT INTO lecturas (
                    master_id, part_number, part_name, supplier_name,
                    ln, an, bn, lv, av, bv, created_at
                ) 
                VALUES (
                    :master_id, :p_num, :p_name, :supplier,
                    :ln, :an, :bn, :lv, :av, :bv, NOW()
                );
            """)
            with engine.begin() as connection:
                connection.execute(insert_query, {
                    "master_id": master_seleccionado,
                    "p_name": part_name_val if part_name_val else "",
                    "p_num": part_number_val,
                    "supplier": supplier_seleccionado,
                    "ln": ln_val,
                    "an": an_val,
                    "bn": bn_val, # Directo desde tu selectbox
                    "lv": lv_val, # Directo desde tu selectbox
                    "av": av_val, # Directo desde tu selectbox
                    "bv": bv_val  # Directo desde tu selectbox
                })

            # 1. Activamos la bandera de sesión
            st.session_state.tiene_lecturas_guardadas = True
            st.success(f"🚀 ¡Lectura guardada exitosamente y vinculada al Master!")

            # 2. Forzamos el redibujado inmediato para desplegar la sección de Excel
            st.rerun()
            
        except Exception as e:
            st.error(f"Error al insertar en la base de datos: {e}")

# Si existe un mensaje de éxito pendiente en la sesión, lo mostramos en pantalla ya recargado
if "mensaje_exito" in st.session_state and st.session_state.mensaje_exito:
    st.success(st.session_state.mensaje_exito)
    # Opcional: Limpiamos la variable para que no se quede fija tras futuras interacciones menores
    st.session_state.mensaje_exito = None

# ==========================================
# 9. CONTROL DE CICLO: NUEVA LECTURA VS FINALIZAR LOTE
# ==========================================
if st.session_state.get('tiene_lecturas_guardadas', False):
    st.markdown("---")
    st.info("💡 **Lectura registrada.** ¿Deseas ingresar otra pieza o terminar la inspección del lote?")

    col_nueva, col_terminar = st.columns(2)
    
    with col_nueva:
        if st.button("➕ Realizar Otra Lectura", use_container_width=True):
            # 1. Desactivamos las banderas de control de lote
            st.session_state.tiene_lecturas_guardadas = False
            st.session_state.mostrar_exportacion_excel = False

            # 2. Limpiamos las llaves de los selectores visuales (Delta L, a, b)
            st.session_state.pop('lv_val', None)
            st.session_state.pop('av_val', None)
            st.session_state.pop('bv_val', None)
            
            # 3. Limpiamos variables de sesión de mediciones para dejar listas para la siguiente pieza
            st.session_state.pop('ln_val', None)
            st.session_state.pop('an_val', None)
            st.session_state.pop('bn_val', None)
            st.session_state.pop('mensaje_exito', None)
            st.rerun()
            
    with col_terminar:
        if st.button("🏁 Finalizar Lote y Descargar Reporte", type="secondary", use_container_width=True):
            st.session_state.mostrar_exportacion_excel = True
            st.rerun()

# ==========================================
# 10. EXPORTACIÓN A EXCEL FILTRADA (Va al final)
# ==========================================
#if st.session_state.get('lectura_guardada', False):
    #st.markdown("---")
    #st.subheader("📊 Exportar Reporte a Excel")

if st.session_state.get('mostrar_exportacion_excel', False):
    st.markdown("---")
    st.subheader("📊 Reporte Consolidado del Lote")

    modo_exportacion = st.radio(
        "Selecciona el alcance del reporte:",
        ["Solo la selección actual (OEM / Master / Parte / Proveedor)", "Todo el histórico de la base de datos"],
        horizontal=True,
        key="radio_export_mode"
    )

    try:
        base_query = """
            SELECT 
                l.id AS "ID Lectura",
                o.oem_name AS "OEM",
                m.master_name AS "Master",
                l.part_number AS "Número de Parte",
                l.part_name AS "Nombre de Parte",
                l.supplier_name AS "Proveedor",
                l.ln AS "L*", l.an AS "a*", l.bn AS "b*",
                l.lv AS "ΔL (Visual)", l.av AS "Δa (Visual)", l.bv AS "Δb (Visual)",
                l.created_at AS "Fecha y Hora"
            FROM lecturas l
            JOIN masters m ON l.master_id = m.id
            JOIN oems o ON m.oem_id = o.id
        """
    
        params = {}
        where_clauses = []

        if modo_exportacion == "Solo la selección actual (OEM / Master / Parte / Proveedor)":
            if oem_seleccionado:
                where_clauses.append("o.id = :oem_id")
                params["oem_id"] = oem_seleccionado
            if master_seleccionado:
                where_clauses.append("m.id = :master_id")
                params["master_id"] = master_seleccionado
            if part_number_val:
                where_clauses.append("l.part_number = :part_num")
                params["part_num"] = part_number_val
            if supplier_seleccionado:
                where_clauses.append("l.supplier_name = :supp_name")
                params["supp_name"] = supplier_seleccionado

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)
    
        base_query += " ORDER BY l.created_at DESC;"

        query_export = sqlalchemy.text(base_query)
        df_lecturas = pd.read_sql(query_export, engine, params=params)

        if not df_lecturas.empty:
        
            if "Fecha y Hora" in df_lecturas.columns:
                df_lecturas["Fecha y Hora"] = pd.to_datetime(df_lecturas["Fecha y Hora"]).dt.tz_localize(None)
        
            st.info(f"Se encontraron **{len(df_lecturas)}** registros listos para exportar bajo los criterios actuales.")
            st.dataframe(df_lecturas.head(5), use_container_width=True)
        
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_lecturas.to_excel(writer, index=False, sheet_name='Colorlink_Reporte')
            buffer.seek(0)

            st.download_button(
                label="📥 Descargar Excel Filtrado (.xlsx)",
                data=buffer,
                file_name="Colorlink_Reporte_Filtrado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )
        else:
            st.warning("⚠️ No existen registros en la base de datos que coincidan con la combinación de filtros seleccionada.")

    except Exception as e:
        st.error(f"Error crítico al generar el reporte filtrado: {e}")
