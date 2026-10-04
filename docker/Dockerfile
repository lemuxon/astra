FROM python:3.11-slim

WORKDIR /app

# Sistem bağımlılıkları
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Paketleri yükle (önce requirements — cache için)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Kaynak dosyaları kopyala
COPY . .

# Dizin hazırlığı
RUN mkdir -p saved_models data logs

# Güvenlik: root olarak çalıştırma
RUN useradd -m -u 1000 astra && chown -R astra:astra /app
USER astra

# Health check için port aç
EXPOSE 8080 9090

# Başlatma
CMD ["python", "main.py", "futures"]
