# Use a stable python 3.11 base
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install OS deps needed by OpenCV / Tesseract / building wheels
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libgl1 \
      libglib2.0-0 \
      libsm6 \
      libxext6 \
      libxrender1 \
      libjpeg-dev \
      zlib1g-dev \
      libpng-dev \
      pkg-config \
      tesseract-ocr \
      libleptonica-dev \
      ca-certificates \
      git \
      curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install python deps first (layer caching)
COPY requirements.txt /app/requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel
# Install from requirements
RUN pip install -r /app/requirements.txt

# Copy the rest of the code
COPY . /app

# Expose port (Render maps $PORT automatically, but 8000 is conventional)
EXPOSE 8000

# Start command
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
