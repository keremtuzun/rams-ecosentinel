FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml /app/
COPY ecosentinel /app/ecosentinel
COPY scripts /app/scripts
RUN pip install --no-cache-dir '.[onnx]'
RUN useradd --create-home --uid 10001 researcher && mkdir -p /app/artifacts && chown researcher /app/artifacts
USER researcher
ENV ECOSENTINEL_ARTIFACTS=/app/artifacts
EXPOSE 8000
CMD ["uvicorn", "ecosentinel.api:app", "--host", "0.0.0.0", "--port", "8000"]
