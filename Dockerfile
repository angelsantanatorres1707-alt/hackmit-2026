# Manim needs real system libraries, so this is a normal container, not a
# serverless function. Vercel/Netlify/Lambda cannot run this image.
#
# Deliberately NO LaTeX: every manim Matrix class shells out to `latex`, so the
# scenes build matrices from Text instead (see backend/scenes/common.py). That
# keeps this image ~700MB instead of ~2.5GB and cuts build time by minutes.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RENDER_CACHE_DIR=/data/cache \
    RENDER_WORK_DIR=/data/jobs

# ffmpeg encodes the video; cairo/pango rasterise every frame and every glyph.
# fonts-dejavu-core is NOT optional: without a font, Text() renders blank and
# does not raise, which is a miserable thing to debug.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libcairo2 \
        libpango-1.0-0 libpangocairo-1.0-0 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Build deps live only in this layer so the final image stays slim: pycairo has
# no manylinux wheel and compiles from source.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config python3-dev \
        libcairo2-dev libpango1.0-dev \
    && pip install --no-cache-dir -r /app/backend/requirements.txt \
    && apt-get purge -y build-essential pkg-config python3-dev \
        libcairo2-dev libpango1.0-dev \
    && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY samples/ /app/samples/

RUN mkdir -p /data/cache /data/jobs

# Renders are cached here. Mount a volume to keep them across restarts.
VOLUME ["/data"]

EXPOSE 8000

# Hosts inject PORT; default to 8000 for plain `docker run`.
CMD ["sh", "-c", "python -m uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
