# Bot Conversacional de Métricas

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


Output con texto + gráficos automáticos cuando aplica.

