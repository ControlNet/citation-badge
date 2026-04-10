FROM python:3.10-slim

ENV HOME=/home/app \
    PUID=1000 \
    PGID=1000 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --no-compile -r requirements.txt

COPY main.py ./
COPY service ./service
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN mkdir -p /data \
    && chown -R app:app /data /home/app \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

VOLUME ["/data"]

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "service.server"]
