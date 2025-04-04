import streamlit as st
import re
import time
import requests
from playwright.sync_api import sync_playwright
import pandas as pd

st.set_page_config(page_title="Consulta SII por RUT", layout="centered")
st.title("🧾 Consulta Pública al SII")

API_KEY = "c846a2f731ab911f1047488da3d232ac"  # Reemplaza con tu API Key real de 2Captcha

def resolver_captcha(image_bytes):
    response = requests.post("http://2captcha.com/in.php", files={"file": ("captcha.jpg", image_bytes)},
                             data={"key": API_KEY, "method": "post", "json": 1})
    data = response.json()
    if data.get("status") != 1:
        raise Exception(f"❌ Error subiendo captcha: {data.get('request')}")
    captcha_id = data["request"]
    for i in range(20):
        time.sleep(5)
        r = requests.get(f"http://2captcha.com/res.php?key={API_KEY}&action=get&id={captcha_id}&json=1")
        data = r.json()
        if data.get("status") == 1:
            return data["request"]
        elif data.get("request") == "CAPCHA_NOT_READY":
            continue
        else:
            raise Exception(f"❌ Error resolviendo captcha: {data.get('request')}")
    raise Exception("❌ Timeout esperando captcha")

def consultar_sii(rut):
    rut_base, dv = rut.strip().split("-")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto("https://zeus.sii.cl/cvc/stc/stc.html", timeout=60000)
            page.wait_for_load_state("load")
            page.fill('#RUT', rut_base)
            page.fill('#DV', dv)
            page.wait_for_selector('#imgcapt', timeout=30000)
            captcha_img = page.locator('#imgcapt')
            captcha_bytes = captcha_img.screenshot()
            captcha_resuelto = resolver_captcha(captcha_bytes)
            page.fill('#txt_code', captcha_resuelto)
            page.click('input[type="submit"]')
            page.wait_for_timeout(6000)
            return page.inner_text('body')
        finally:
            browser.close()

rut_input = st.text_input("Ingresa el RUT (con guión):", "12345678-9")

if st.button("Consultar"):
    try:
        with st.spinner("Consultando..."):
            resultado = consultar_sii(rut_input)

        st.success("✅ Consulta realizada correctamente")

        if "RUT Contribuyente" not in resultado:
            st.error("❌ No se pudo obtener información del contribuyente. Verifica si el captcha fue resuelto correctamente.")
            st.text_area("HTML recibido:", resultado, height=300)
        else:
            # === EXTRAER DATOS CLAVE ===
            data = {}
            patrones = {
                "RUT Contribuyente": r"RUT Contribuyente\s*:\s*(\d+-\d)",
                "Nombre / Razón Social": r"Nombre o Razón Social\s*:\s*(.*)",
                "Fecha Consulta": r"Fecha de realización de la consulta:\s*(.*)",
                "Inicio Actividades": r"Contribuyente presenta Inicio de Actividades:\s*(SI|NO)",
                "Fecha de Inicio de Actividades": r"Fecha de Inicio de Actividades:\s*(.*)",
                "Empresa Menor Tamaño": r"Contribuyente es Empresa de Menor Tamaño.*:\s*(SI|NO)",
                "Moneda Extranjera": r"para declarar y pagar sus impuestos en moneda extranjera:\s*(SI|NO)"
            }

            for campo, regex in patrones.items():
                match = re.search(regex, resultado, re.IGNORECASE)
                data[campo] = match.group(1).strip() if match else "No disponible"

            st.markdown("### 🧾 Datos del Contribuyente")
            st.table(pd.DataFrame(list(data.items()), columns=["Campo", "Valor"]))

            # === ACTIVIDADES ECONÓMICAS ===
            actividades = re.findall(r"^(.*?)\s+(\d{6})\s+(Primera|Segunda)\s+(SI|NO|No)\s+(\d{2}-\d{2}-\d{4})", resultado, re.MULTILINE)
            if actividades:
                st.markdown("### 🛠 Actividades Económicas Vigentes")
                df_actividades = pd.DataFrame(actividades, columns=["Actividad", "Código", "Categoría", "Afecta IVA", "Fecha"])
                st.dataframe(df_actividades)

            # === DOCUMENTOS TIMBRADOS ===
            st.markdown("### 🧾 Documentos Timbrados")
            documentos = []

            doc_start = resultado.find("Documentos Timbrados:")
            doc_end = resultado.find("Para informarse sobre un documento específico", doc_start)

            if doc_start != -1 and doc_end != -1:
                bloque_doc = resultado[doc_start:doc_end]
                lineas = bloque_doc.strip().splitlines()

                for linea in lineas:
                    match = re.match(r"^(.*?)(\d{4})$", linea.strip())
                    if match:
                        documento = match.group(1).strip()
                        anio = match.group(2).strip()
                        documentos.append({"Documento": documento, "Año último timbraje": anio})

            if documentos:
                st.table(pd.DataFrame(documentos))
            else:
                st.warning("No se encontraron documentos timbrados para este RUT.")

            # === RECOMENDACIÓN GENERAL ===
            recomendaciones = re.findall(r"(?i)recomendaci[oó]n general.*?(?=Servicio de Impuestos Internos|\Z)", resultado, re.DOTALL)
            if recomendaciones:
                st.markdown("### ⚠️ Recomendación General del SII")
                st.warning(recomendaciones[0].strip())

            # === TEXTO COMPLETO ===
            with st.expander("📄 Ver resultado completo del SII"):
                st.text_area("Texto original extraído del SII", resultado, height=400)

    except Exception as e:
        st.error(f"❌ Error durante la consulta: {e}")
