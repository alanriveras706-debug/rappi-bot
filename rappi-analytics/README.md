# Rappi Analytics — Bot Conversacional de Métricas

Bot + insights automáticos para métricas operacionales de Rappi en LATAM.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Crea un archivo `.env` en la raíz:
```
OPENAI_API_KEY=tu-api-key-aqui
```

## Uso

```bash
streamlit run app.py
```

Se abre en `http://localhost:####`. Dos tabs: bot conversacional e insights automáticos.

**Ejemplos de preguntas:**
- "¿Cuáles son las 5 zonas con mayor Lead Penetration esta semana?"
- "Compara el Perfect Order entre Wealthy y Non Wealthy en México"
- "Muestra la evolución de Gross Profit en Chapinero últimas 8 semanas"

Output con texto + gráficos automáticos cuando aplica.

