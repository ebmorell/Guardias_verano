import streamlit as st
import pandas as pd
from datetime import datetime
from ortools.sat.python import cp_model
import io

# 🔒 Sección de pago
st.markdown("### 🔒 Activar acceso completo")
st.markdown(
    """
    Para acceder a todas las funcionalidades del planificador de guardias, realiza un pago único.

    👉 [**Haz clic aquí para pagar**](https://buy.stripe.com/test_4gM4gB1ID6Ova3OaoW3wQ00)
    """,
    unsafe_allow_html=True
)



st.set_page_config(page_title="Asignador de Guardias", layout="wide")
st.title("🩺 Asignador de Guardias Médicas")

archivo = st.file_uploader("📤 Sube el archivo Excel con vacaciones y especialidad", type=["xlsx"])

if archivo:
    vacaciones_df = pd.read_excel(archivo)
    vacaciones_df["Fecha inicio"] = pd.to_datetime(vacaciones_df["Fecha inicio"])
    vacaciones_df["Fecha fin"] = pd.to_datetime(vacaciones_df["Fecha fin"])

    medicos_df = vacaciones_df.drop_duplicates(subset="Medico")[["Medico", "especialidad"]].copy()
    medicos = medicos_df["Medico"].tolist()
    especialidades = medicos_df["especialidad"].tolist()
    medico_idx = {m: i for i, m in enumerate(medicos)}
    especialidad_dict = dict(zip(medicos, especialidades))

    st.subheader("📆 Periodo de guardias")
    start_date = st.date_input("Inicio", datetime(2025, 7, 1))
    end_date = st.date_input("Fin", datetime(2025, 9, 30))

    calendar = pd.DataFrame({"Fecha": pd.date_range(start=start_date, end=end_date, freq='D')})
    calendar["Tipo de día"] = calendar["Fecha"].apply(lambda x: "Fin de semana" if x.weekday() >= 5 else "Laborable")
    calendar["Mes"] = calendar["Fecha"].dt.to_period("M")

    st.subheader("🎉 Días festivos")
    festivos = st.multiselect(
        "Selecciona los días festivos:",
        options=calendar["Fecha"],
        format_func=lambda x: x.strftime("%A %d/%m/%Y")
    )
    calendar["Tipo de día"] = calendar.apply(
        lambda row: "Festivo" if row["Fecha"] in festivos else row["Tipo de día"], axis=1
    )

    st.header("⚙️ Parámetros de asignación")
    dias_entre_guardias = st.slider("📆 Días mínimos entre guardias", 1, 5, 3)
    max_guardias_mes = st.slider("📅 Máximo de guardias por mes", 1, 10, 4)
    medicos_por_dia = st.slider("👥 Número de médicos por día", 1, 5, 3)
    evitar_misma_especialidad = st.checkbox("🚫 Evitar coincidencia de misma especialidad", value=True)

    st.subheader("🔒 Restricciones individuales")
    with st.expander("➕ Añadir restricciones personalizadas"):
        restricciones_individuales = []
        num_restricciones = st.number_input("¿Cuántas restricciones quieres añadir?", min_value=0, max_value=50, value=0)
        for i in range(num_restricciones):
            col1, col2 = st.columns(2)
            with col1:
                nombre = st.selectbox(f"👤 Médico #{i+1}", options=medicos, key=f"medico_{i}")
            with col2:
                fecha_restringida = st.date_input(f"📅 Día bloqueado", key=f"fecha_{i}")
            restricciones_individuales.append((nombre, fecha_restringida))

    if st.button("📅 Generar calendario de guardias"):
        num_dias = len(calendar)
        num_medicos = len(medicos)
        model = cp_model.CpModel()
        x = {(m, d): model.NewBoolVar(f"x_{m}_{d}") for m in range(num_medicos) for d in range(num_dias)}

        # 1. Médicos por día
        for d in range(num_dias):
            model.Add(sum(x[m, d] for m in range(num_medicos)) == medicos_por_dia)

        # 2. Vacaciones
        for _, row in vacaciones_df.iterrows():
            m = medico_idx[row["Medico"]]
            for d in range(num_dias):
                fecha = calendar.iloc[d]["Fecha"]
                if row["Fecha inicio"] <= fecha <= row["Fecha fin"]:
                    model.Add(x[m, d] == 0)

        # 3. Restricciones individuales
        for nombre, fecha_restringida in restricciones_individuales:
            fecha = pd.to_datetime(fecha_restringida)
            if nombre in medico_idx and fecha in calendar["Fecha"].values:
                m = medico_idx[nombre]
                d = calendar[calendar["Fecha"] == fecha].index[0]
                model.Add(x[m, d] == 0)

        # 4. Mínimos días entre guardias
        for m in range(num_medicos):
            for d in range(num_dias - dias_entre_guardias):
                model.Add(sum(x[m, d+i] for i in range(dias_entre_guardias+1)) <= 1)

        # 5. Máximo guardias al mes
        meses = calendar["Mes"].unique()
        for m in range(num_medicos):
            for mes in meses:
                dias_mes = calendar[calendar["Mes"] == mes].index.tolist()
                model.Add(sum(x[m, d] for d in dias_mes) <= max_guardias_mes)

        # 6. Reparto equitativo total
        total_guardias = num_dias * medicos_por_dia
        min_guardias = total_guardias // num_medicos
        max_guardias = min_guardias + (1 if total_guardias % num_medicos > 0 else 0)
        for m in range(num_medicos):
            model.Add(sum(x[m, d] for d in range(num_dias)) >= min_guardias)
            model.Add(sum(x[m, d] for d in range(num_dias)) <= max_guardias)

        # 7. Reparto equitativo fines de semana
        fds_indices = [i for i, tipo in enumerate(calendar["Tipo de día"]) if tipo == "Fin de semana"]
        total_fds_guardias = len(fds_indices) * medicos_por_dia
        min_fds = total_fds_guardias // num_medicos
        max_fds = min_fds + (1 if total_fds_guardias % num_medicos > 0 else 0)
        for m in range(num_medicos):
            model.Add(sum(x[m, d] for d in fds_indices) >= min_fds)
            model.Add(sum(x[m, d] for d in fds_indices) <= max_fds)

        # 8. No repetir especialidad en un mismo día
        if evitar_misma_especialidad:
            especialidades_unicas = list(set(especialidades))
            for d in range(num_dias):
                for esp in especialidades_unicas:
                    indices = [i for i, m in enumerate(medicos) if especialidad_dict[m] == esp]
                    if len(indices) > 1:
                        model.Add(sum(x[m, d] for m in indices) <= 1)

        # Resolver
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 60.0
        status = solver.Solve(model)

        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            resultados = []
            for d in range(num_dias):
                fecha = calendar.iloc[d]["Fecha"]
                tipo = calendar.iloc[d]["Tipo de día"]
                medicos_dia = [medicos[m] for m in range(num_medicos) if solver.Value(x[m, d]) == 1]
                while len(medicos_dia) < medicos_por_dia:
                    medicos_dia.append("")
                fila = {"Fecha": fecha, "Tipo de día": tipo}
                for i in range(medicos_por_dia):
                    fila[f"Médico {i+1}"] = medicos_dia[i]
                resultados.append(fila)

            df_final = pd.DataFrame(resultados)
            st.success("✅ Guardias generadas correctamente")
            st.dataframe(df_final)

            # Descargar Excel
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_final.to_excel(writer, index=False, sheet_name="Guardias")
            output.seek(0)

            st.download_button(
                label="📥 Descargar Excel",
                data=output,
                file_name="Guardias_por_dia.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.error("❌ No se encontró una solución factible. Prueba relajando alguna restricción.")
