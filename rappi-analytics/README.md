# Rappi Analytics - Sistema de Análisis Inteligente

Bot conversacional + insights automáticos para métricas operacionales de Rappi.

## ¿Qué hace?

Básicamente es un chatbot que te deja hacer preguntas sobre datos de operaciones de Rappi en lenguaje normal, sin necesidad de saber SQL o Python. También genera reportes automáticos con insights semanales.

**Ejemplo:**
- "¿Cuáles son las 5 zonas con mayor Lead Penetration esta semana?"
- "Compara el Perfect Order entre zonas Wealthy y Non Wealthy en México"
- "Muestra la evolución de Gross Profit en Chapinero últimas 8 semanas"

El sistema automáticamente procesa los datos, genera la respuesta y crea gráficos cuando tiene sentido.

## Stack

- **Frontend/Backend:** Streamlit (todo en uno, rápido para MVPs)
- **LLM:** OpenAI GPT-4o con tool calling
- **Data:** Pandas para procesamiento
- **Visualizaciones:** Plotly

## Instalación

1. Clonar el repo
```bash
git clone [tu-repo-url]
cd rappi-analytics
```

2. Instalar dependencias
```bash
pip install -r requirements.txt
```

3. Configurar API key

Crea un archivo `.env` en la raíz del proyecto:
```
OPENAI_API_KEY=tu-api-key-aqui
```

4. Correr la app
```bash
streamlit run app.py
```

Se abre automáticamente en `http://localhost:####`

## Estructura del Proyecto

```
rappi-analytics/
├── app.py                 # Aplicación principal
├── data/
│   ├── metrics.csv        # Métricas operacionales por zona
│   ├── orders.csv         # Volumen de órdenes por zona
│   └── summary.csv        # Diccionario de columnas (schema)
├── .env                   # API keys (no subir a git)
├── requirements.txt       # Dependencias
└── README.md
```

## Cómo Funciona

1. Usuario escribe pregunta en lenguaje natural
2. Streamlit envía mensaje a GPT-4o con 7 herramientas disponibles
3. GPT-4o decide qué herramientas necesita y con qué parámetros
4. Las funciones Python se ejecutan con Pandas
5. GPT-4o genera respuesta interpretando los resultados
6. Streamlit muestra respuesta + gráficos automáticos

## Herramientas Disponibles

El bot tiene acceso a estas funciones:

- `top_zones` - Top N zonas por métrica
- `average_by_group` - Promedios por país/ciudad/tipo
- `compare_zone_types` - Wealthy vs Non Wealthy
- `zone_trend` - Evolución semanal de métrica en zona
- `orders_trend` - Evolución semanal de órdenes
- `growing_zones` - Zonas con mayor crecimiento
- `high_metric_low_metric` - Alto en una métrica, bajo en otra

## Insights Automáticos

El tab "Insights Automáticos" genera un reporte ejecutivo detectando:

- **Anomalías:** Cambios drásticos >10% semana a semana
- **Tendencias preocupantes:** Deterioro sostenido 3+ semanas
- **Benchmarking:** Zonas que divergen de su grupo (z-score)
- **Correlaciones:** Relaciones entre métricas (Pearson ≥0.5)
- **Oportunidades:** Zonas con fuerte crecimiento en órdenes

## Limitaciones

- Solo funciona en local (no hay deployment)
- Dataset estático de 9 semanas
- Sin autenticación
- Depende 100% de OpenAI API

## Costos

~$0.003 por query. Para un equipo de 10 personas haciendo 20 queries diarias = ~$12/mes.

## Next Steps

Si tuviera más tiempo:
- Deployment en Railway/Render
- Conexión a DB real en vez de CSVs
- Visualizaciones más ricas (mapas de calor, gráficos combinados)
- Explicabilidad (mostrar SQL/Pandas equivalente)
- Integración con Slack


## Autor

Fernando Rivera
