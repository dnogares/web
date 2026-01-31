FROM python:3.10-slim

# Instalar dependencias del sistema necesarias para GDAL y GeoPandas
RUN apt-get update && apt-get install -y \
    build-essential \
    libgdal-dev \
    gdal-bin \
    python3-gdal \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Configurar variables de entorno para GDAL
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Configurar directorio de trabajo
WORKDIR /app

# Copiar requirements primero para aprovechar caché de Docker
COPY requirements.txt .

# Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Crear directorio para capas (punto de montaje para volumen)
RUN mkdir -p /app/capas

# Exponer el puerto 80 (HTTP estándar)
EXPOSE 80

# Comando de inicio optimizado para FastAPI
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
