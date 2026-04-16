# Stage 1: Build
FROM python:3.11-slim as builder

WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .

# Instalar dependências Python em um diretório virtual
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Instalar apenas as dependências de runtime necessárias
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copiar venv do builder
COPY --from=builder /opt/venv /opt/venv

# Copiar aplicação
COPY gate_detector_app.py .

# Criar diretório de logs
RUN mkdir -p /app/logs

# Configurar PATH
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

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
