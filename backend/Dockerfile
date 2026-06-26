FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU-only torch first, then everything else
RUN pip install --no-cache-dir \
    torch==2.11.0+cpu --extra-index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir transformers nltk && \
    pip install --no-cache-dir -r requirements.txt

# Download NLI model and NLTK data at build time
RUN python -c "from transformers import AutoTokenizer, AutoModelForSequenceClassification; AutoTokenizer.from_pretrained('cross-encoder/nli-deberta-v3-small'); AutoModelForSequenceClassification.from_pretrained('cross-encoder/nli-deberta-v3-small')"
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab')"

COPY . .

RUN mkdir -p data/uploads data/chroma

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
