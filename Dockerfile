FROM python:3.10-slim

# Instalar dependencias del sistema mínimas necesarias
# libgl1: necesario para matplotlib/plots
# gdal-bin: útil para herramientas de línea de comandos si se necesitan
RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1 \
    gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# Configurar directorio de trabajo
WORKDIR /app

# Actualizar pip
RUN pip install --upgrade pip

# Copiar requirements
COPY requirements.txt .

# Instalar dependencias de Python
# --prefer-binary intenta usar wheels precompilados para evitar errores de compilación de GDAL/GEOS
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# Copiar el resto del código
COPY . .

# Crear directorio para capas
RUN mkdir -p /app/capas

# Exponer el puerto 80
EXPOSE 80

# Comando de inicio
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
