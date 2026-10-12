import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from PIL import Image
import base64

# 1. Cargar el logo
logo_path = "apple-touch-icon.png"  # o "Colorlink_ONCLOUD_logo.png"
Colorlink_ONCLOUD_logo = Image.open(logo_path)

# 2. Convertir la imagen a Base64 para iOS
with open(logo_path, "rb") as image_file:
    encoded_string = base64.b64encode(image_file.read()).decode()

logo_base64 = f"data:image/png;base64,{encoded_string}"

# 3. Configurar la página (esto cambiará el icono de la pestaña)
st.set_page_config(
    page_title="Colorlink Vision",
    page_icon=Colorlink_ONCLOUD_logo,  # Streamlit ajustará automáticamente el tamaño para el favicon
    layout="centered"
)
# 4. Inyectar el icono codificado directamente en el HTML para Safari/iOS
st.markdown(
    f"""
    <head>
        <link rel="apple-touch-icon" href="{logo_base64}">
        <link rel="shortcut icon" href="{logo_base64}">
    </head>
    """,
    unsafe_allow_html=True
)

# 5. MOSTRAR EL LOGO EN LA PANTALLA
st.image(Colorlink_ONCLOUD_logo, width=200) # Se muestra aquí, arriba del título
st.title("Colorlink Vision")
st.caption("Extracción automática de deltas y coordenadas CIELAB desde fotos o capturas de espectrofotómetros.")

# --- Resto de tu código ---

# 1. Autenticación con Gemini API Key
# Intenta obtener la clave desde los Secretos de Streamlit Cloud o pide la clave en pantalla
api_key = st.secrets.get("GEMINI_API_KEY", None)

if not api_key:
    api_key = st.sidebar.text_input("Gemini API Key", type="password")

if not api_key:
    st.info("👈 Introduce tu Gemini API Key en el menú lateral o configúrala en los Secrets para comenzar.")
    st.stop()

client = genai.Client(api_key=api_key)

# 2. Esquema estricto Pydantic para la extracción metrológica
class DatosEspectro(BaseModel):
    equipo_software: str = Field(description="Modelo de equipo o software si aparece (ej. CM-3700A / SpectraMagic NX)")
    muestra_id: str = Field(description="Número o identificador de muestra/lote si existe")
    
    # Patrón / Estándar
    patron_L: float = Field(description="L del patrón")
    patron_a: float = Field(description="a del patrón")
    patron_b: float = Field(description="b del patrón")
    
    # Muestra Medida
    medido_L: float = Field(description="L* medido")
    medido_a: float = Field(description="a* medido")
    medido_b: float = Field(description="b* medido")
    
    # Desviaciones (Deltas)
    delta_L: float = Field(description="dL* / Delta L")
    delta_a: float = Field(description="da* / Delta a")
    delta_b: float = Field(description="db* / Delta b")
    
    delta_E: float = Field(description="dE*ab / Delta E total")
    veredicto: str = Field(description="Aprobación si existe: PASS, FAIL, ACEPTADO, RECHAZADO, etc.")
    comentario: str = Field(description="Texto o comentario al pie del reporte si existe")

# 3. Captura de Imagen (Optimizada para pantalla táctil y escritorio)
st.subheader("1. Captura o Carga la Lectura")

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

if imagen_cargada:
    st.image(imagen_cargada, caption="Lectura seleccionada", use_column_width=True)
    
    # 4. Procesamiento con Gemini Vision
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
                    model="gemini-3.8-flash",
                    contents=[imagen_cargada, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=DatosEspectro,
                        temperature=0.0
                    )
                )
                
                datos = DatosEspectro.model_validate_json(response.text)
                
                st.success("¡Lectura completada!")
                
                # Desviaciones Principales (Deltas)
                st.markdown("### 📊 Desviaciones (Deltas)")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("dL*", datos.delta_L)
                m2.metric("da*", datos.delta_a)
                m3.metric("db*", datos.delta_b)
                m4.metric("dE*ab", datos.delta_E)
                
                # Tabla Comparativa Completa
                st.markdown("### 📑 Detalle Metrológico")
                tabla_comparativa = {
                    "Parámetro": ["L (Luminosidad)", "a (Verde-Rojo)", "b (Azul-Amarillo)"],
                    "Patrón / Master": [datos.patron_L, datos.patron_a, datos.patron_b],
                    "Muestra Medida": [datos.medido_L, datos.medido_a, datos.medido_b],
                    "Delta (Desviación)": [datos.delta_L, datos.delta_a, datos.delta_b]
                }
                st.dataframe(tabla_comparativa, use_container_width=True)
                
                # Información Adicional
                st.info(f"**Veredicto:** {datos.veredicto} | **Muestra/Lote:** {datos.muestra_id}\n\n**Comentario:** {datos.comentario}")
                
                # Formato JSON listo para copiar o enviar
                with st.expander("Ver formato JSON (para enviar a la BD)"):
                    st.json(datos.model_dump())

            except Exception as e:
                st.error(f"Error al procesar la imagen: {e}")
