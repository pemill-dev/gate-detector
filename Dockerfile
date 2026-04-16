# Use imagem Python 3.11 slim como base (compatível com ultralytics 8.0.x)
FROM python:3.11-slim

# Definir diretório de trabalho
WORKDIR /app

# Instalar dependências do sistema necessárias
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    ffmpeg \
    libopenblas-dev \
    liblapack-dev \
    libatlas-base-dev \
    gfortran \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements.txt
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Criar diretório de logs
RUN mkdir -p /app/logs

# Copiar aplicação
COPY gate_detector_app.py .

# Variáveis de ambiente padrão
ENV DVR_HOST=192.168.0.21
ENV DVR_PORT=80
ENV DVR_USER=manus
ENV DVR_PASS=Teste123
ENV CAMERA_INDEX=2
ENV GATE_API_URL=http://api-v2.pemill.com.br/open/dor/2
ENV GATE_COOLDOWN_SECONDS=60
ENV CONFIDENCE_THRESHOLD=0.5

# Executar aplicação
CMD ["python", "gate_detector_app.py"]
