"""
Rappi Analytics - Bot Conversacional + Insights Automaticos
Ejecutar: streamlit run app.py
"""
import os
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from openai import OpenAI, AuthenticationError, APIConnectionError, RateLimitError
import markdown as md
from dotenv import load_dotenv

load_dotenv(override=True)

# ─── Constantes ──────────────────────────────────────────────────────────────

WEEK_COLS_M = [f"L{i}W_ROLL" for i in range(8, -1, -1)]   # L8W_ROLL … L0W_ROLL
WEEK_COLS_O = [f"L{i}W" for i in range(8, -1, -1)]         # L8W … L0W
WEEK_LABELS = ["W-8", "W-7", "W-6", "W-5",
               "W-4", "W-3", "W-2", "W-1", "W0 (actual)"]

METRICS_DICT = {
    "% PRO Users Who Breakeven": "Usuarios Pro cuyo valor generado cubre el costo de membresía / Total usuarios Pro",
    "% Restaurants Sessions With Optimal Assortment": "Sesiones con mínimo 40 restaurantes / Total sesiones",
    "Gross Profit UE": "Margen bruto de ganancia / Total de órdenes",
    "Lead Penetration": "Tiendas habilitadas en Rappi / (Leads + Habilitadas + Salidas)",
    "MLTV Top Verticals Adoption": "Usuarios con órdenes en múltiples verticales / Total usuarios",
    "Non-Pro PTC > OP": "Conversión No-Pro de Proceed to Checkout a Order Placed",
    "Perfect Orders": "Órdenes sin cancelaciones, defectos o demora / Total órdenes",
    "Pro Adoption (Last Week Status)": "Usuarios suscripción Pro / Total usuarios de Rappi",
    "Restaurants Markdowns / GMV": "Descuentos totales en restaurantes / GMV restaurantes",
    "Restaurants SS > ATC CVR": "Conversión en restaurantes de Select Store a Add to Cart",
    "Restaurants SST > SS CVR": "Usuarios que seleccionan tienda tras elegir vertical Restaurantes",
    "Retail SST > SS CVR": "Usuarios que seleccionan tienda tras elegir Supermercados",
    "Turbo Adoption": "Usuarios que compran en Turbo / Total usuarios con tiendas Turbo disponibles",
}

def _build_system_prompt(df_summary: pd.DataFrame) -> str:
    schema_lines = "\n".join(
        f"- {row['Column']} ({row['Type']}): {row['Description (inferred)']}"
        for _, row in df_summary.iterrows()
    )
    return f"""Eres un analista de datos experto en operaciones de Rappi para Latinoamérica.
Tienes acceso a métricas operacionales y órdenes por zona geográfica de 9 países (AR, BR, CL, CO, CR, EC, MX, PE, UY).

Contexto de negocio:
- "zonas problemáticas" = zonas con Perfect Orders bajo, Gross Profit UE bajo o métricas deterioradas
- "zonas de oportunidad" = buen volumen de órdenes pero métricas mejorables
- Los datos tienen 9 semanas: L8W (hace 8 semanas) hasta L0W (semana actual)
- ZONE_TYPE: Wealthy / Non Wealthy | ZONE_PRIORITIZATION: High Priority / Prioritized / Not Prioritized

Schema de columnas:
{schema_lines}

Métricas disponibles: {", ".join(METRICS_DICT.keys())}

Instrucciones:
1. Usa SIEMPRE las herramientas para obtener datos reales antes de responder
2. Interpreta los resultados con contexto de negocio (no solo números)
3. Sugiere análisis adicionales relevantes al final de cada respuesta
4. Responde en español, de forma concisa y accionable"""


# ─── Carga de datos ──────────────────────────────────────────────────────────

@st.cache_data
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data_dir = Path(__file__).parent / "data"
    df_m = pd.read_csv(data_dir / "metrics.csv")
    df_o = pd.read_csv(data_dir / "orders.csv")
    df_s = pd.read_csv(data_dir / "summary.csv")

    # Las métricas tienen coma como separador decimal ->convertir a punto
    for col in WEEK_COLS_M:
        if col in df_m.columns:
            df_m[col] = (
                df_m[col].astype(str)
                .str.replace(",", ".", regex=False)
                .pipe(pd.to_numeric, errors="coerce")
            )

    for col in ["COUNTRY", "CITY", "ZONE", "ZONE_TYPE", "ZONE_PRIORITIZATION", "METRIC"]:
        if col in df_m.columns:
            df_m[col] = df_m[col].astype(str).str.strip()

    for col in ["COUNTRY", "CITY", "ZONE", "METRIC"]:
        if col in df_o.columns:
            df_o[col] = df_o[col].astype(str).str.strip()

    return df_m, df_o, df_s


def _find_metric(df_m: pd.DataFrame, query: str) -> pd.DataFrame:
    """Busca una métrica por nombre (parcial, case-insensitive)."""
    q = query.lower()
    return df_m[df_m["METRIC"].str.lower().str.contains(q, na=False)]


def _find_zone(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Busca una zona por nombre (parcial, case-insensitive)."""
    q = query.lower()
    return df[df["ZONE"].str.lower().str.contains(q, na=False)]


# ─── Herramientas (tools) ─────────────────────────────────────────────────────

def top_zones(metric: str, n: int = 5, order: str = "desc", country: str = None) -> dict:
    """Top N zonas por valor actual de una métrica."""
    df_m, _, _ = load_data()
    df = _find_metric(df_m, metric)
    if df.empty:
        return {"error": f"Métrica '{metric}' no encontrada. Disponibles: {list(METRICS_DICT.keys())}"}

    if country:
        df = df[df["COUNTRY"].str.upper() == country.upper()]
        if df.empty:
            return {"error": f"No hay datos para el país '{country}'"}

    metric_name = df["METRIC"].iloc[0]
    df = df[["COUNTRY", "CITY", "ZONE", "ZONE_TYPE", "L0W_ROLL"]].dropna()
    df = df.sort_values("L0W_ROLL", ascending=(order == "asc")).head(n)
    df["L0W_ROLL"] = df["L0W_ROLL"].round(4)

    return {
        "metric": metric_name,
        "week": "actual (L0W)",
        "order": order,
        "results": df.rename(columns={"L0W_ROLL": "value"}).to_dict(orient="records"),
    }


def average_by_group(metric: str, group_by: str = "country") -> dict:
    """Promedio de una métrica agrupado por país, ciudad o tipo de zona."""
    df_m, _, _ = load_data()
    df = _find_metric(df_m, metric)
    if df.empty:
        return {"error": f"Métrica '{metric}' no encontrada"}

    col_map = {"country": "COUNTRY", "city": "CITY", "zone_type": "ZONE_TYPE",
               "prioritization": "ZONE_PRIORITIZATION"}
    group_col = col_map.get(group_by.lower(), "COUNTRY")

    metric_name = df["METRIC"].iloc[0]
    result = (
        df.groupby(group_col)["L0W_ROLL"]
        .agg(mean="mean", median="median", count="count")
        .round(4)
        .sort_values("mean", ascending=False)
        .reset_index()
    )
    return {
        "metric": metric_name,
        "group_by": group_by,
        "results": result.to_dict(orient="records"),
    }


def compare_zone_types(metric: str, country: str = None) -> dict:
    """Compara Wealthy vs Non Wealthy en una métrica."""
    df_m, _, _ = load_data()
    df = _find_metric(df_m, metric)
    if df.empty:
        return {"error": f"Métrica '{metric}' no encontrada"}

    if country:
        df = df[df["COUNTRY"].str.upper() == country.upper()]

    metric_name = df["METRIC"].iloc[0]
    result = (
        df.groupby("ZONE_TYPE")["L0W_ROLL"]
        .agg(mean="mean", median="median", count="count")
        .round(4)
        .reset_index()
    )
    # Diferencia porcentual
    vals = result.set_index("ZONE_TYPE")["mean"].to_dict()
    diff = None
    if "Wealthy" in vals and "Non Wealthy" in vals and vals["Non Wealthy"] != 0:
        diff = round((vals.get("Wealthy", 0) -
                     vals.get("Non Wealthy", 0)) / vals["Non Wealthy"] * 100, 2)

    return {
        "metric": metric_name,
        "country": country or "todos",
        "comparison": result.to_dict(orient="records"),
        "wealthy_vs_non_wealthy_diff_pct": diff,
    }


def zone_trend(zone: str, metric: str, n_weeks: int = 8) -> dict:
    """Evolución semanal de una métrica en una zona."""
    df_m, _, _ = load_data()
    df = _find_metric(df_m, metric)
    df = _find_zone(df, zone)

    if df.empty:
        return {"error": f"No se encontró zona '{zone}' con métrica '{metric}'"}

    row = df.iloc[0]
    n = min(n_weeks, len(WEEK_COLS_M))
    cols = WEEK_COLS_M[-n:]
    labels = WEEK_LABELS[-n:]

    trend = [
        {"week": lbl, "col": col, "value": round(
            float(row[col]), 4) if pd.notna(row[col]) else None}
        for col, lbl in zip(cols, labels)
    ]

    # Cambio semana-a-semana
    values = [t["value"] for t in trend if t["value"] is not None]
    change_wow = None
    if len(values) >= 2 and values[-2] != 0:
        change_wow = round(
            (values[-1] - values[-2]) / abs(values[-2]) * 100, 2)

    return {
        "zone": row["ZONE"],
        "country": row["COUNTRY"],
        "metric": row["METRIC"],
        "trend": trend,
        "change_last_week_pct": change_wow,
    }


def orders_trend(zone: str, n_weeks: int = 8) -> dict:
    """Evolución semanal de órdenes en una zona."""
    _, df_o, _ = load_data()
    df = _find_zone(df_o, zone)

    if df.empty:
        return {"error": f"No se encontró zona '{zone}' en datos de órdenes"}

    row = df.iloc[0]
    n = min(n_weeks, len(WEEK_COLS_O))
    cols = WEEK_COLS_O[-n:]
    labels = WEEK_LABELS[-n:]

    trend = [
        {"week": lbl, "orders": int(row[col]) if pd.notna(row[col]) else None}
        for col, lbl in zip(cols, labels)
    ]

    return {"zone": row["ZONE"], "country": row["COUNTRY"], "trend": trend}


def growing_zones(n_weeks: int = 5, top_n: int = 10) -> dict:
    """Zonas con mayor crecimiento en órdenes en las últimas N semanas."""
    _, df_o, _ = load_data()
    cols = WEEK_COLS_O[-n_weeks:]

    df = df_o[["COUNTRY", "CITY", "ZONE"] + cols].dropna().copy()
    df = df[df[cols[0]] > 0]  # evitar división por cero
    df["growth_pct"] = ((df[cols[-1]] - df[cols[0]]) /
                        df[cols[0]] * 100).round(2)
    df["orders_current"] = df[cols[-1]].astype(int)

    top = df.sort_values("growth_pct", ascending=False).head(top_n)

    return {
        "n_weeks": n_weeks,
        "period": f"{cols[0]} ->{cols[-1]}",
        "results": top[["COUNTRY", "CITY", "ZONE", "growth_pct", "orders_current"]].to_dict(orient="records"),
    }


def high_metric_low_metric(high_metric: str, low_metric: str, country: str = None) -> dict:
    """Zonas con alto valor en una métrica y bajo en otra simultáneamente."""
    df_m, _, _ = load_data()

    df_h = _find_metric(df_m, high_metric)
    df_l = _find_metric(df_m, low_metric)

    if df_h.empty:
        return {"error": f"Métrica '{high_metric}' no encontrada"}
    if df_l.empty:
        return {"error": f"Métrica '{low_metric}' no encontrada"}

    if country:
        df_h = df_h[df_h["COUNTRY"].str.upper() == country.upper()]
        df_l = df_l[df_l["COUNTRY"].str.upper() == country.upper()]

    h_name = df_h["METRIC"].iloc[0]
    l_name = df_l["METRIC"].iloc[0]

    high_thresh = df_h["L0W_ROLL"].quantile(0.65)
    low_thresh = df_l["L0W_ROLL"].quantile(0.35)

    high_zones = set(df_h[df_h["L0W_ROLL"] >= high_thresh]["ZONE"])
    low_zones = set(df_l[df_l["L0W_ROLL"] <= low_thresh]["ZONE"])
    matching = high_zones & low_zones

    if not matching:
        return {"message": "No se encontraron zonas que cumplan ambas condiciones con los umbrales actuales."}

    df_result = (
        df_h[df_h["ZONE"].isin(matching)][["ZONE", "COUNTRY", "L0W_ROLL"]]
        .rename(columns={"L0W_ROLL": "high_value"})
        .merge(
            df_l[df_l["ZONE"].isin(matching)][["ZONE", "L0W_ROLL"]].rename(
                columns={"L0W_ROLL": "low_value"}),
            on="ZONE",
        )
        .round(4)
    )

    return {
        "high_metric": h_name,
        "low_metric": l_name,
        "threshold_high": round(high_thresh, 4),
        "threshold_low": round(low_thresh, 4),
        "zones_found": len(matching),
        "results": df_result.head(20).to_dict(orient="records"),
    }


# ─── Definición de tools (formato OpenAI) ────────────────────────────────────

def _tool(name: str, description: str, properties: dict, required: list = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


OAI_TOOLS = [
    _tool("top_zones", "Top N zonas por valor actual de una métrica.", {
        "metric": {"type": "string", "description": "Nombre o parte del nombre de la métrica"},
        "n": {"type": "integer", "description": "Número de zonas (default 5)"},
        "order": {"type": "string", "enum": ["desc", "asc"]},
        "country": {"type": "string", "description": "Código de país (AR,BR,CL,CO,CR,EC,MX,PE,UY)"},
    }, ["metric"]),
    _tool("average_by_group", "Promedio de una métrica agrupado por país/ciudad/tipo.", {
        "metric": {"type": "string"},
        "group_by": {"type": "string", "enum": ["country", "city", "zone_type", "prioritization"]},
    }, ["metric"]),
    _tool("compare_zone_types", "Compara Wealthy vs Non Wealthy en una métrica.", {
        "metric": {"type": "string"},
        "country": {"type": "string", "description": "Filtrar por país (opcional)"},
    }, ["metric"]),
    _tool("zone_trend", "Evolución semanal de una métrica en una zona.", {
        "zone": {"type": "string", "description": "Nombre o parte del nombre de la zona"},
        "metric": {"type": "string"},
        "n_weeks": {"type": "integer", "description": "Semanas a mostrar (2-9, default 8)"},
    }, ["zone", "metric"]),
    _tool("orders_trend", "Evolución semanal de órdenes en una zona.", {
        "zone": {"type": "string"},
        "n_weeks": {"type": "integer", "description": "Semanas (2-9, default 8)"},
    }, ["zone"]),
    _tool("growing_zones", "Zonas con mayor crecimiento en órdenes en las últimas N semanas.", {
        "n_weeks": {"type": "integer", "description": "Ventana de semanas (default 5)"},
        "top_n": {"type": "integer", "description": "Número de zonas (default 10)"},
    }),
    _tool("high_metric_low_metric", "Zonas con alto valor en una métrica y bajo en otra.", {
        "high_metric": {"type": "string"},
        "low_metric": {"type": "string"},
        "country": {"type": "string", "description": "Filtrar por país (opcional)"},
    }, ["high_metric", "low_metric"]),
]

TOOL_FUNCTIONS = {
    "top_zones": top_zones,
    "average_by_group": average_by_group,
    "compare_zone_types": compare_zone_types,
    "zone_trend": zone_trend,
    "orders_trend": orders_trend,
    "growing_zones": growing_zones,
    "high_metric_low_metric": high_metric_low_metric,
}


# ─── Generación de gráficos ───────────────────────────────────────────────────

def make_chart(tool_name: str, tool_input: dict, result: dict):  # noqa: ARG001
    """Genera un gráfico Plotly según el tipo de herramienta y datos retornados."""
    if "error" in result or "message" in result:
        return None

    try:
        if tool_name in ("zone_trend", "orders_trend"):
            trend = result.get("trend", [])
            if not trend:
                return None
            df = pd.DataFrame(trend)
            y_col = "value" if "value" in df.columns else "orders"
            title = f"{result.get('metric', 'Órdenes')} -{result.get('zone', '')}"
            out = px.line(df, x="week", y=y_col, title=title, markers=True)
            out.update_layout(xaxis_title="Semana", yaxis_title=y_col.capitalize(), height=350)
            return out

        if tool_name == "top_zones":
            df = pd.DataFrame(result.get("results", []))
            if df.empty:
                return None
            out = px.bar(
                df.sort_values("value"),
                x="value", y="ZONE", orientation="h",
                title=f"Top zonas -{result.get('metric', '')}",
                color="ZONE_TYPE" if "ZONE_TYPE" in df.columns else None,
                height=max(300, len(df) * 45),
            )
            out.update_layout(yaxis_title="", xaxis_title="Valor (semana actual)")
            return out

        if tool_name == "average_by_group":
            df = pd.DataFrame(result.get("results", []))
            if df.empty:
                return None
            group_col = df.columns[0]
            out = px.bar(
                df.sort_values("mean"),
                x="mean", y=group_col, orientation="h",
                title=f"Promedio por {result.get('group_by', '')} -{result.get('metric', '')}",
                height=max(300, len(df) * 45),
            )
            out.update_layout(yaxis_title="", xaxis_title="Promedio")
            return out

        if tool_name == "compare_zone_types":
            df = pd.DataFrame(result.get("comparison", []))
            if df.empty:
                return None
            out = px.bar(
                df, x="ZONE_TYPE", y="mean",
                title=f"Wealthy vs Non Wealthy -{result.get('metric', '')}",
                color="ZONE_TYPE",
                error_y=None,
                height=350,
            )
            out.update_layout(xaxis_title="", yaxis_title="Promedio")
            return out

        if tool_name == "growing_zones":
            df = pd.DataFrame(result.get("results", []))
            if df.empty:
                return None
            out = px.bar(
                df.sort_values("growth_pct"),
                x="growth_pct", y="ZONE", orientation="h",
                title=f"Zonas con mayor crecimiento ({result.get('n_weeks', 5)} sem.)",
                color="COUNTRY",
                height=max(300, len(df) * 45),
            )
            out.update_layout(yaxis_title="", xaxis_title="Crecimiento (%)")
            return out

    except (KeyError, ValueError, TypeError):
        pass

    return None


# ─── Chat con Claude (tool use loop) ─────────────────────────────────────────

def chat_with_claude(user_message: str, conv_history: list) -> tuple[str, list]:
    """Envía el mensaje a OpenAI con tool use. Retorna (respuesta_texto, charts)."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Error:Falta OPENAI_API_KEY en el archivo .env", []
    client = OpenAI(api_key=api_key)
    _, _, df_summary = load_data()
    try:
        return _chat_loop(client, user_message, conv_history, df_summary)
    except AuthenticationError:
        return (
            "Error:API key inválida. Verifica OPENAI_API_KEY en `.env` "
            "y reinicia con **Ctrl+C** ->`streamlit run app.py`."
        ), []
    except (APIConnectionError, RateLimitError) as exc:
        return f"Error:Error de API: {exc}", []


def _chat_loop(
    client: OpenAI,
    user_message: str,
    conv_history: list,
    df_summary: pd.DataFrame,
) -> tuple[str, list]:
    messages = [{"role": "system", "content": _build_system_prompt(df_summary)}]
    messages += [{"role": h["role"], "content": h["content"]} for h in conv_history]
    messages.append({"role": "user", "content": user_message})

    result_charts: list = []

    while True:
        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=2048,
            tools=OAI_TOOLS,
            messages=messages,
        )

        choice = response.choices[0]
        msg = choice.message

        if choice.finish_reason == "stop":
            return msg.content or "No se pudo generar una respuesta.", result_charts

        if choice.finish_reason == "tool_calls" and msg.tool_calls:
            messages.append(msg)  # assistant message with tool_calls
            for tc in msg.tool_calls:
                fn = TOOL_FUNCTIONS.get(tc.function.name)
                tool_input = json.loads(tc.function.arguments)
                tool_out = (
                    fn(**tool_input) if fn
                    else {"error": f"Tool '{tc.function.name}' no existe"}
                )
                new_chart = make_chart(tc.function.name, tool_input, tool_out)
                if new_chart:
                    result_charts.append(new_chart)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_out, ensure_ascii=False),
                })
        else:
            return msg.content or "No se pudo generar una respuesta.", result_charts


# ─── Insights automáticos ─────────────────────────────────────────────────────

def _declining_trends(df: pd.DataFrame) -> list:
    """Zonas con deterioro consecutivo en 3+ semanas."""
    result = []
    for _, row in df.iterrows():
        vals = [row[c] for c in ["L3W_ROLL", "L2W_ROLL", "L1W_ROLL", "L0W_ROLL"] if pd.notna(row[c])]
        if len(vals) == 4 and all(vals[k] > vals[k + 1] for k in range(3)):
            drop = (vals[-1] - vals[0]) / abs(vals[0]) * 100 if vals[0] != 0 else 0
            result.append({
                "COUNTRY": row["COUNTRY"], "CITY": row["CITY"], "ZONE": row["ZONE"],
                "METRIC": row["METRIC"], "drop_pct": round(drop, 2),
                "L3W": round(vals[0], 4), "L0W": round(vals[3], 4),
            })
    return sorted(result, key=lambda x: x["drop_pct"])[:20]


def _metric_correlations(df: pd.DataFrame) -> list:
    """Pares de métricas con correlación de Pearson >= 0.5."""
    pivot = df.pivot_table(index=["COUNTRY", "CITY", "ZONE"], columns="METRIC", values="L0W_ROLL")
    corr = pivot.corr(numeric_only=True).round(3)
    cols = corr.columns.tolist()
    pairs = [
        {"metric_a": cols[ci], "metric_b": cols[cj], "correlation": corr.iloc[ci, cj]}
        for ci, _ in enumerate(cols)
        for cj in range(ci + 1, len(cols))
        if abs(corr.iloc[ci, cj]) >= 0.5
    ]
    return sorted(pairs, key=lambda x: abs(x["correlation"]), reverse=True)[:15]


def compute_insights() -> dict:
    """Calcula insights con pandas puro. Retorna dict con hallazgos."""
    df_raw, df_o, _ = load_data()
    df_m = df_raw.copy()  # evitar mutar el DataFrame cacheado

    # 1. Anomalías: cambio > 10% semana a semana (L1W ->L0W)
    df_m["wow_change"] = (df_m["L0W_ROLL"] - df_m["L1W_ROLL"]) / df_m["L1W_ROLL"].abs() * 100
    anomalies = (
        df_m[df_m["wow_change"].abs() > 10]
        .dropna(subset=["wow_change"])
        .replace([float("inf"), float("-inf")], pd.NA)
        .dropna(subset=["wow_change"])
        .pipe(lambda d: d[d["wow_change"].abs() <= 500])  # excluir outliers extremos
    )

    # 3. Benchmarking: z-score por grupo (país + tipo + métrica)
    df_m["group_mean"] = df_m.groupby(["COUNTRY", "ZONE_TYPE", "METRIC"])["L0W_ROLL"].transform("mean")
    df_m["z_score"] = (
        (df_m["L0W_ROLL"] - df_m["group_mean"])
        / df_m.groupby(["COUNTRY", "ZONE_TYPE", "METRIC"])["L0W_ROLL"].transform("std")
    )
    outliers = df_m[df_m["z_score"].abs() > 2].dropna(subset=["z_score"])

    # 5. Crecimiento de órdenes (últimas 5 semanas)
    order_cols = WEEK_COLS_O[-5:]
    df_grow = df_o[["COUNTRY", "CITY", "ZONE"] + order_cols].dropna().copy()
    df_grow = df_grow[df_grow[order_cols[0]] > 0]
    df_grow["growth_pct"] = (
        (df_grow[order_cols[-1]] - df_grow[order_cols[0]]) / df_grow[order_cols[0]] * 100
    ).round(2)

    return {
        "anomalies": (
            anomalies.sort_values("wow_change", key=abs, ascending=False)
            .head(20)[["COUNTRY", "CITY", "ZONE", "METRIC", "L1W_ROLL", "L0W_ROLL", "wow_change"]]
            .round(4).to_dict(orient="records")
        ),
        "declining_trends": _declining_trends(df_m),
        "benchmarking": (
            outliers.sort_values("z_score", key=abs, ascending=False)
            .head(15)[["COUNTRY", "CITY", "ZONE", "ZONE_TYPE", "METRIC", "L0W_ROLL", "group_mean", "z_score"]]
            .round(4).to_dict(orient="records")
        ),
        "correlations": _metric_correlations(df_m),
        "opportunities": (
            df_grow.sort_values("growth_pct", ascending=False)
            .head(10)[["COUNTRY", "CITY", "ZONE", "growth_pct"]]
            .to_dict(orient="records")
        ),
    }


def generate_insights_report(insights: dict) -> str:
    """Envía los insights a OpenAI para que redacte el reporte ejecutivo."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Error:Falta OPENAI_API_KEY en el archivo `.env`."

    prompt = (
        "Eres un analista senior de operaciones de Rappi. "
        "Con base en el siguiente análisis automático de datos, "
        "redacta un **reporte ejecutivo** en español.\n\n"
        f"DATOS ANALIZADOS:\n{json.dumps(insights, ensure_ascii=False, indent=2)}\n\n"
        "FORMATO DEL REPORTE:\n"
        "1. **Resumen Ejecutivo** -Top 3-5 hallazgos críticos\n"
        "2. **Anomalías Detectadas** -Zonas con cambios drásticos esta semana\n"
        "3. **Tendencias Preocupantes** -Métricas en deterioro sostenido\n"
        "4. **Benchmarking** -Zonas divergentes vs su grupo\n"
        "5. **Correlaciones Relevantes** -Relaciones entre métricas\n"
        "6. **Oportunidades** -Zonas con fuerte crecimiento en órdenes\n"
        "7. **Recomendaciones Accionables** -3-5 acciones concretas priorizadas\n\n"
        "Sé conciso, usa bullet points, enfócate en lo accionable. Usa formato Markdown."
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=3000,
            messages=[
                {"role": "system", "content": "Eres un analista senior de operaciones de Rappi."},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""
    except AuthenticationError:
        return (
            "Error:API key inválida. Verifica OPENAI_API_KEY en `.env` "
            "y reinicia con **Ctrl+C** ->`streamlit run app.py`."
        )
    except (APIConnectionError, RateLimitError) as exc:
        return f"Error:Error de API: {exc}"


# ─── UI Streamlit ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Rappi Analytics",
    layout="wide",
)

st.title("Sistema de Análisis Inteligente para Operaciones Rappi")

if not os.getenv("OPENAI_API_KEY"):
    st.error("Falta la variable OPENAI_API_KEY. Crea un archivo .env con tu clave.")
    st.stop()

tab_chat, tab_insights = st.tabs(["Bot Conversacional", "Insights Automaticos"])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 -BOT CONVERSACIONAL
# ═══════════════════════════════════════════════════════════════════════════════
with tab_chat:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "charts" not in st.session_state:
        st.session_state.charts = {}

    if st.button("Limpiar conversacion"):
        st.session_state.messages = []
        st.session_state.charts = {}
        st.rerun()

    for idx, chat_msg in enumerate(st.session_state.messages):
        with st.chat_message(chat_msg["role"]):
            st.markdown(chat_msg["content"])
            for display_chart in st.session_state.charts.get(idx, []):
                st.plotly_chart(display_chart, use_container_width=True)

    user_input = st.chat_input("Escribe tu pregunta aqui...")

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Analizando datos..."):
                chat_history = st.session_state.messages[:-1]
                answer, response_charts = chat_with_claude(user_input, chat_history)

            st.markdown(answer)
            for display_chart in response_charts:
                st.plotly_chart(display_chart, use_container_width=True)

        msg_index = len(st.session_state.messages)
        st.session_state.messages.append({"role": "assistant", "content": answer})
        if response_charts:
            st.session_state.charts[msg_index] = response_charts


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 -INSIGHTS AUTOMATICOS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_insights:
    col1, col2 = st.columns([1, 3])

    def _build_insight_charts(data: dict) -> list:
        """Genera las figuras Plotly de insights. Retorna lista de figuras."""
        figs = []

        if data.get("anomalies"):
            df_anom = pd.DataFrame(data["anomalies"]).head(10).copy()
            df_anom["wow_change"] = pd.to_numeric(df_anom["wow_change"], errors="coerce")
            df_anom = df_anom.dropna(subset=["wow_change"])
            df_anom["abs_change"] = df_anom["wow_change"].abs().round(2)
            df_anom["direccion"] = df_anom["wow_change"].apply(
                lambda x: "mejora" if x > 0 else "deterioro"
            )
            df_anom = df_anom.sort_values("abs_change", ascending=True)
            f = px.bar(
                df_anom, x="abs_change", y="ZONE", orientation="h",
                color="direccion",
                color_discrete_map={"mejora": "#2ecc71", "deterioro": "#e74c3c"},
                title="Anomalias: mayor cambio WoW (%)",
                labels={"abs_change": "Cambio absoluto (%)"},
                height=max(300, len(df_anom) * 45),
            )
            f.update_layout(xaxis_range=[0, df_anom["abs_change"].max() * 1.15])
            figs.append(f)

        if data.get("opportunities"):
            df_opp = pd.DataFrame(data["opportunities"])
            figs.append(px.bar(
                df_opp.sort_values("growth_pct"),
                x="growth_pct", y="ZONE", orientation="h",
                color="COUNTRY", title="Top zonas con crecimiento en ordenes (5 sem.)",
                height=400,
            ))

        if data.get("declining_trends"):
            df_dec = pd.DataFrame(data["declining_trends"]).head(10)
            figs.append(px.bar(
                df_dec.sort_values("drop_pct"),
                x="drop_pct", y="ZONE", orientation="h",
                color="METRIC", title="Tendencias en deterioro sostenido (3+ semanas)",
                height=400,
            ))

        return figs

    with col1:
        generate_btn = st.button("Generar Reporte", type="primary", use_container_width=True)
        if "insights_report" in st.session_state:
            data_dl = st.session_state.insights_data
            html_body = md.markdown(
                st.session_state.insights_report,
                extensions=["tables", "fenced_code"],
            )
            charts_html = "".join(
                f.to_html(full_html=False, include_plotlyjs=False)
                for f in _build_insight_charts(data_dl)
            )
            html_page = (
                '<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
                "<title>Rappi Insights Report</title>"
                '<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>'
                "</head><body>"
                f"{html_body}<hr>{charts_html}"
                "</body></html>"
            )
            st.download_button(
                "Descargar (.html)",
                data=html_page,
                file_name="rappi-insights-report.html",
                mime="text/html",
                use_container_width=True,
            )

    if generate_btn:
        with st.spinner("Analizando datos y generando reporte..."):
            insights_data = compute_insights()
            report = generate_insights_report(insights_data)
            st.session_state.insights_report = report
            st.session_state.insights_data = insights_data

    if "insights_report" in st.session_state:
        with col2:
            st.markdown(st.session_state.insights_report)

        st.divider()
        st.subheader("Visualizaciones del analisis")

        data = st.session_state.insights_data
        c1, c2 = st.columns(2)
        insight_figs = _build_insight_charts(data)

        if len(insight_figs) > 0:
            with c1:
                st.plotly_chart(insight_figs[0], use_container_width=True)
        if len(insight_figs) > 1:
            with c2:
                st.plotly_chart(insight_figs[1], use_container_width=True)
        if len(insight_figs) > 2:
            st.plotly_chart(insight_figs[2], use_container_width=True)
