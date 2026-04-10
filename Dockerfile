FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . ./

EXPOSE 8000

VOLUME ["/data"]

CMD ["python", "-m", "service.server"]
