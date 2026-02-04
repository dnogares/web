FROM python:3.10-slim

# Configuración para instalaciones no interactivas
ENV DEBIAN_FRONTEND=noninteractive
ENV TERM=linux

# Instalar dependencias del sistema necesarias para GeoPandas y GDAL
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    libspatialindex-dev \
    g++ \
    # Dependencias adicionales para matplotlib/plotly
    libfreetype6-dev \
    libpng-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Configurar variables de entorno para GDAL
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Directorio de trabajo
WORKDIR /app

# Copiar requirements e instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Exponer el puerto (EasyPanel usa 80 por defecto internamente)
ENV PORT=80
EXPOSE 80

# Comando de inicio con uvicorn directamente
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
