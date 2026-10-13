import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from PIL import Image
import base64

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
st.caption("Extracción automática de deltas y coordenadas CIELAB con registro en Supabase.")

# ==========================================
# 2. CONEXIÓN A SUPABASE Y GEMINI API
# ==========================================
try:
    conn = st.connection("postgresql", type="sql")
except Exception as e:
    st.error(f"Error al conectar con Supabase: {e}")
    st.stop()

api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    api_key = st.sidebar.text_input("Gemini API Key", type="password")

if not api_key:
    st.info("👈 Introduce tu Gemini API Key en el menú lateral o configúrala en los Secrets para comenzar.")
    st.stop()

client = genai.Client(api_key=api_key)

# ==========================================
# 3. ESQUEMA PYDANTIC PARA EXTRACCIÓN
# ==========================================
class DatosEspectro(BaseModel):
    equipo_software: str = Field(description="Modelo de equipo o software si aparece (ej. CM-3700A / SpectraMagic NX)")
    muestra_id: str = Field(description="Número o identificador de muestra/lote si existe")
    
    patron_L: float = Field(description="L del patrón")
    patron_a: float = Field(description="a del patrón")
    patron_b: float = Field(description="b del patrón")
    
    medido_L: float = Field(description="L* medido")
    medido_a: float = Field(description="a* medido")
    medido_b: float = Field(description="b* medido")
    
    delta_L: float = Field(description="dL* / Delta L")
    delta_a: float = Field(description="da* / Delta a")
    delta_b: float = Field(description="db* / Delta b")
    
    delta_E: float = Field(description="dE*ab / Delta E total")
    veredicto: str = Field(description="Aprobación si existe: PASS, FAIL, ACEPTADO, RECHAZADO, etc.")
    comentario: str = Field(description="Texto o comentario al pie del reporte si existe")

# ==========================================
# 4. SELECCIÓN EN CASCADA Y REGISTRO NUEVO
# ==========================================
st.subheader("1. Identificación de la Pieza (Jerarquía)")

oem_seleccionado = None
master_seleccionado = None
part_number_val = None
part_name_val = None
supplier_seleccionado = None

try:
    # --- NIVEL 1: OEM ---
    df_oems = conn.query("SELECT DISTINCT oem_name FROM lecturas WHERE oem_name IS NOT NULL ORDER BY oem_name;", ttl=0)
    lista_oems = df_oems["oem_name"].tolist() if not df_oems.empty else []
    lista_oems.append("➕ Agregar nuevo OEM...")

    oem_choice = st.selectbox("OEM", lista_oems)
    if oem_choice == "➕ Agregar nuevo OEM...":
        oem_seleccionado = st.text_input("Escribe el nombre del nuevo OEM:")
    else:
        oem_seleccionado = oem_choice

    if oem_seleccionado and oem_seleccionado != "Selecciona un OEM...":
        
        # --- NIVEL 2: MASTER ---
        df_masters = conn.query(
            f"SELECT DISTINCT master_name FROM lecturas WHERE oem_name = '{oem_seleccionado}' AND master_name IS NOT NULL ORDER BY master_name;", 
            ttl=0
        )
        lista_masters = df_masters["master_name"].tolist() if not df_masters.empty else []
        lista_masters.append("➕ Agregar nuevo Master...")

        master_choice = st.selectbox("Master Name", lista_masters)
        if master_choice == "➕ Agregar nuevo Master...":
            master_seleccionado = st.text_input("Escribe el nombre del nuevo Master:")
        else:
            master_seleccionado = master_choice

        if master_seleccionado and master_seleccionado != "Selecciona un Master...":
            
            # --- NIVEL 3: PARTE (Number y Name) ---
            df_parts = conn.query(
                f"SELECT DISTINCT part_number, part_name FROM lecturas WHERE oem_name = '{oem_seleccionado}' AND master_name = '{master_seleccionado}' AND part_number IS NOT NULL;", 
                ttl=0
            )
            lista_parts = []
            if not df_parts.empty:
                df_parts['display'] = df_parts['part_number'].astype(str) + " - " + df_parts['part_name'].fillna('')
                lista_parts = df_parts['display'].tolist()
            lista_parts.append("➕ Agregar nueva Parte...")

            part_choice = st.selectbox("Part Number / Name", lista_parts)
            if part_choice == "➕ Agregar nueva Parte...":
                col_pn, col_pname = st.columns(2)
                with col_pn:
                    part_number_val = st.text_input("Número de Parte:")
                with col_pname:
                    part_name_val = st.text_input("Nombre de la Parte:")
            else:
                if " - " in part_choice:
                    part_number_val = part_choice.split(" - ")[0]
                    part_name_val = part_choice.split(" - ")[1]
                else:
                    part_number_val = part_choice
                    part_name_val = ""

            if part_number_val:
                # --- NIVEL 4: SUPPLIER ---
                df_suppliers = conn.query(
                    f"SELECT DISTINCT supplier_name FROM lecturas WHERE oem_name = '{oem_seleccionado}' AND master_name = '{master_seleccionado}' AND part_number = '{part_number_val}' AND supplier_name IS NOT NULL;", 
                    ttl=0
                )
                lista_suppliers = df_suppliers["supplier_name"].tolist() if not df_suppliers.empty else []
                lista_suppliers.append("➕ Agregar nuevo Proveedor...")

                supplier_choice = st.selectbox("Supplier Name", lista_suppliers)
                if supplier_choice == "➕ Agregar nuevo Proveedor...":
                    supplier_seleccionado = st.text_input("Escribe el nombre del nuevo Proveedor:")
                else:
                    supplier_seleccionado = supplier_choice

except Exception as e:
    st.warning(f"Nota: Los menús interactivos se están inicializando. ({e})")

st.markdown("---")

# ==========================================
# 5. CAPTURA Y ANÁLISIS DE IMAGEN CON GEMINI
# ==========================================
st.subheader("2. Captura o Carga la Lectura")

opcion_carga = st.radio("Selecciona origen de la imagen:", ["Subir Foto / Archivo / Screenshot", "Usar Cámara Directa"])
imagen_cargada = None

if opcion_carga == "Subir Foto / Archivo / Screenshot":
    archivo = st.file_uploader("Selecciona archivo o pega imagen", type=["jpg", "jpeg", "png"])
    if archivo:
        imagen_cargada = Image.open(archivo)
else:
    foto = st.camera_input("Toma una foto a la pantalla del espectrofotómetro")
    if foto:
        imagen_cargada = Image.open(foto)

ln_val, an_val, bn_val = 52.40, 12.10, -2.30

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
                
                Asegúrate de conservar el signo numérico correcto (+/-) en los deltas.
                """
                
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[imagen_cargada, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=DatosEspectro,
                        temperature=0.0
                    )
                )
                
                datos = DatosEspectro.model_validate_json(response.text)
                st.success("¡Lectura completada!")
                
                ln_val = datos.medido_L
                an_val = datos.medido_a
                bn_val = datos.medido_b

                st.markdown("### 📊 Desviaciones (Deltas)")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("dL*", datos.delta_L)
                m2.metric("da*", datos.delta_a)
                m3.metric("db*", datos.delta_b)
                m4.metric("dE*ab", datos.delta_E)
                
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
                st.error(f"Error al procesar la imagen: {e}")

st.markdown("---")

# ==========================================
# 6. VALORES FINALES Y EVALUACIÓN VISUAL (-3 a 3)
# ==========================================
st.subheader("3. Confirmación de Valores y Evaluación Visual")

col_l, col_a, col_b = st.columns(3)
with col_l:
    ln_val = st.number_input("L* (ln)", value=float(ln_val), format="%.2f")
with col_a:
    an_val = st.number_input("a* (an)", value=float(an_val), format="%.2f")
with col_b:
    bn_val = st.number_input("b* (bn)", value=float(bn_val), format="%.2f")

st.markdown("#### Evaluación Visual por Eje (-3 a 3)")
st.caption("0 = color exacto | ±1, ±2 = aprobado | ±3 = rechazado")

col_vl, col_va, col_vb = st.columns(3)
with col_vl:
    lv_val = st.selectbox("Eval Eje L (lv)", [-3, -2, -1, 0, 1, 2, 3], index=3)
with col_va:
    av_val = st.selectbox("Eval Eje a (av)", [-3, -2, -1, 0, 1, 2, 3], index=3)
with col_vb:
    bv_val = st.selectbox("Eval Eje b (bv)", [-3, -2, -1, 0, 1, 2, 3], index=3)

st.markdown("---")

# ==========================================
# 7. BOTÓN DE GUARDADO EN SUPABASE
# ==========================================
if st.button("💾 Guardar Lectura en la Nube", type="primary", use_container_width=True):
    if not oem_seleccionado or oem_seleccionado == "Selecciona un OEM..." or \
       not master_seleccionado or master_seleccionado == "Selecciona un Master..." or \
       not supplier_seleccionado or supplier_seleccionado == "Selecciona Proveedor...":
        st.warning("⚠️ Por favor completa o agrega los campos de la jerarquía (OEM, Master, Parte y Proveedor) antes de guardar.")
    else:
        try:
            query = """
                INSERT INTO lecturas (
                    oem_name, master_name, part_name, part_number, supplier_name,
                    ln, an, bn, lv, av, bv, created_at
                ) 
                VALUES (
                    :oem, :master, :p_name, :p_num, :supplier,
                    :ln, :an, :bn, :lv, :av, :bv, NOW()
                );
            """
            with conn.session as s:
                s.execute(query, {
                    "oem": oem_seleccionado,
                    "master": master_seleccionado,
                    "p_name": part_name_val,
                    "p_num": part_number_val,
                    "supplier": supplier_seleccionado,
                    "ln": ln_val,
                    "an": an_val,
                    "bn": bn_val,
                    "lv": lv_val,
                    "av": av_val,
                    "bv": bv_val
                })
                s.commit()
                
            st.success(f"🚀 ¡Lectura guardada exitosamente para **{oem_seleccionado}** (Parte: {part_number_val})!")
        except Exception as e:
            st.error(f"Error al insertar en la base de datos: {e}")
