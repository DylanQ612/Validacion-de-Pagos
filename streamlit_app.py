import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from datetime import datetime

st.set_page_config(
    page_title="Validacion de Pagos",
    page_icon="💳",
    layout="centered"
)

st.title("💳 Validacion de Pagos")
st.markdown("### Sistema de Control de Interfaces")

st.info("""
**Instrucciones:**
1. Sube el archivo de **Pagos STP** (.xlsx)
2. Sube el archivo de **Reporte de Ingresos** (.xls o .xlsx)
3. Haz clic en **Procesar** para generar el reporte
""")

def procesar_pagos_stp(file):
    try:
        df = pd.read_excel(file, engine='openpyxl')
        if 'Monto' in df.columns:
            df['Monto'] = df['Monto'].astype(str).str.replace(',', '').str.replace('$', '').str.strip()
            df['Monto'] = pd.to_numeric(df['Monto'], errors='coerce')
        if 'NumeroClienteSAP' in df.columns:
            df['NumeroClienteSAP'] = pd.to_numeric(df['NumeroClienteSAP'], errors='coerce')
        df = df.dropna(subset=['NumeroClienteSAP', 'Monto'])

        # Filtrar clientes que empiezan con 9999
        df = df[~df['NumeroClienteSAP'].astype(str).str.startswith('9999')]

        tabla_dinamica = df.groupby('NumeroClienteSAP')['Monto'].sum().reset_index()
        tabla_dinamica.columns = ['ID_CLIENTE', 'Monto_STP']
        return tabla_dinamica
    except Exception as e:
        raise Exception(f"Error procesando Pagos STP: {str(e)}")

def procesar_reporte_ingresos(file):
    try:
        file.seek(0)
        file_content = file.read()
        file.seek(0)

        if file_content.startswith(b'<') or b'<html' in file_content[:100].lower():
            df = pd.read_html(BytesIO(file_content))[0]
            if all(str(col).isdigit() for col in df.columns):
                df.columns = df.iloc[0]
                df = df[1:].reset_index(drop=True)
        else:
            filename = file.name.lower()
            if filename.endswith('.xls'):
                df = pd.read_excel(file, engine='xlrd')
            else:
                df = pd.read_excel(file, engine='openpyxl')

        df.columns = [str(col).strip() for col in df.columns]

        if 'SUCURSAL' in df.columns:
            df = df[df['SUCURSAL'].astype(str) == '99']
        if 'ESTATUS' in df.columns:
            df = df[df['ESTATUS'] == 'Activo']
        if 'METODO DE PAGO' in df.columns:
            df_stp = df[df['METODO DE PAGO'] == 'STP-03'].copy()
        else:
            df_stp = df.copy()

        if 'NO. CLIENTE' not in df_stp.columns or 'TOTAL' not in df_stp.columns:
            raise Exception(f"Columnas requeridas no encontradas. Columnas disponibles: {list(df.columns)}")

        if 'NO. CLIENTE' in df_stp.columns:
            df_stp['NO. CLIENTE'] = pd.to_numeric(df_stp['NO. CLIENTE'], errors='coerce')
        if 'TOTAL' in df_stp.columns:
            df_stp['TOTAL'] = df_stp['TOTAL'].astype(str).str.replace(',', '').str.replace('$', '').str.strip()
            df_stp['TOTAL'] = pd.to_numeric(df_stp['TOTAL'], errors='coerce')
        df_stp = df_stp.dropna(subset=['NO. CLIENTE', 'TOTAL'])
        tabla_dinamica = df_stp.groupby('NO. CLIENTE')['TOTAL'].sum().reset_index()
        tabla_dinamica.columns = ['ID_CLIENTE', 'Monto_Reportado']

        df_completo = df.copy()
        if 'NO. CLIENTE' in df_completo.columns:
            df_completo['NO. CLIENTE'] = pd.to_numeric(df_completo['NO. CLIENTE'], errors='coerce')
        if 'TOTAL' in df_completo.columns:
            df_completo['TOTAL'] = df_completo['TOTAL'].astype(str).str.replace(',', '').str.replace('$', '').str.strip()
            df_completo['TOTAL'] = pd.to_numeric(df_completo['TOTAL'], errors='coerce')
        df_completo = df_completo.dropna(subset=['NO. CLIENTE', 'TOTAL'])

        return tabla_dinamica, df_completo
    except Exception as e:
        raise Exception(f"Error procesando Reporte Ingresos: {str(e)}")

def buscar_pago_en_otros_metodos(id_cliente, monto_faltante, df_completo, monto_stp_actual):
    pagos_cliente = df_completo[(df_completo['NO. CLIENTE'] == id_cliente) & (df_completo['METODO DE PAGO'] != 'STP-03')]
    if len(pagos_cliente) == 0:
        return False
    for _, pago in pagos_cliente.iterrows():
        if abs(pago['TOTAL'] - monto_faltante) < 0.01:
            return True
    montos = pagos_cliente['TOTAL'].values
    for i in range(len(montos)):
        for j in range(i+1, len(montos)):
            if abs(montos[i] + montos[j] - monto_faltante) < 0.01:
                return True
    return False

def detectar_irregularidades(tabla_stp, tabla_ingresos, df_completo_ingresos):
    resultado = pd.merge(tabla_stp, tabla_ingresos, on='ID_CLIENTE', how='outer')
    resultado['Monto_STP'] = resultado['Monto_STP'].fillna(0)
    resultado['Monto_Reportado'] = resultado['Monto_Reportado'].fillna(0)
    resultado['Diferencia'] = resultado['Monto_STP'] - resultado['Monto_Reportado']
    resultado['Motivo'] = ''

    for idx, row in resultado.iterrows():
        monto_stp = row['Monto_STP']
        monto_reportado = row['Monto_Reportado']
        diferencia = row['Diferencia']

        if monto_reportado == 0:
            resultado.at[idx, 'Motivo'] = 'Sin pago aplicado en POS'
        elif abs(diferencia) <= 15:
            resultado.at[idx, 'Motivo'] = 'OK'
        elif monto_stp > 0 and monto_reportado > monto_stp:
            ratio = monto_reportado / monto_stp
            if abs(ratio - round(ratio)) < 0.01 and ratio >= 2:
                n_veces = int(round(ratio))
                resultado.at[idx, 'Motivo'] = f'Pago duplicado ({n_veces} veces)'
            else:
                resultado.at[idx, 'Motivo'] = 'Diferencia'
        elif monto_stp > monto_reportado:
            monto_faltante = monto_stp - monto_reportado
            id_cliente = row['ID_CLIENTE']
            if buscar_pago_en_otros_metodos(id_cliente, monto_faltante, df_completo_ingresos, monto_reportado):
                resultado.at[idx, 'Motivo'] = 'Captura como otro medio de pago'
            else:
                resultado.at[idx, 'Motivo'] = 'Diferencia'
        else:
            resultado.at[idx, 'Motivo'] = 'Diferencia'

    resultado = resultado[['ID_CLIENTE', 'Monto_STP', 'Monto_Reportado', 'Diferencia', 'Motivo']]
    resultado['Diferencia_Abs'] = abs(resultado['Diferencia'])
    resultado = resultado.sort_values('Diferencia_Abs', ascending=False)
    resultado = resultado.drop('Diferencia_Abs', axis=1)

    return resultado

col1, col2 = st.columns(2)

with col1:
    archivo_stp = st.file_uploader(
        "📄 Archivo de Pagos STP (.xlsx)",
        type=['xlsx'],
        help="Sube el archivo de pagos reales recibidos en el sistema"
    )

with col2:
    archivo_ingresos = st.file_uploader(
        "📄 Reporte de Ingresos (.xls, .xlsx)",
        type=['xls', 'xlsx'],
        help="Sube el archivo de datos capturados en tiendas"
    )

if st.button("🔍 Procesar Archivos", type="primary", width='stretch'):
    if archivo_stp is None or archivo_ingresos is None:
        st.error("❌ Por favor sube ambos archivos antes de procesar")
    else:
        try:
            with st.spinner("Procesando archivos..."):
                tabla_stp = procesar_pagos_stp(archivo_stp)
                tabla_ingresos, df_completo = procesar_reporte_ingresos(archivo_ingresos)
                resultado = detectar_irregularidades(tabla_stp, tabla_ingresos, df_completo)

                st.success("✅ Archivos procesados exitosamente!")

                st.markdown("### 📊 Resumen de Irregularidades")
                resumen = resultado['Motivo'].value_counts().reset_index()
                resumen.columns = ['Motivo', 'Cantidad']
                st.dataframe(resumen, width='stretch', hide_index=True)

                st.markdown("### 📋 Resultados Detallados")
                st.dataframe(resultado, width='stretch', hide_index=True)

                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    resultado.to_excel(writer, sheet_name='Validacion', index=False)
                    resumen.to_excel(writer, sheet_name='Resumen', index=False)
                output.seek(0)

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                nombre_archivo = f'Validacion_Pagos_{timestamp}.xlsx'

                st.download_button(
                    label="📥 Descargar Reporte Excel",
                    data=output,
                    file_name=nombre_archivo,
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    width='stretch'
                )

        except Exception as e:
            st.error(f"❌ Error al procesar: {str(e)}")

st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666; font-size: 0.9em;'>
Sistema de Validacion de Pagos - Control de Interfaces
</div>
""", unsafe_allow_html=True)
