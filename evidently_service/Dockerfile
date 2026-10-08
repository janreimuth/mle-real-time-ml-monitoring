FROM ghcr.io/astral-sh/uv:0.11.19 AS uv
FROM python:3.13-slim-bookworm

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project --no-cache

COPY webservice/ ./webservice/
COPY evidently_service/ ./evidently_service/

EXPOSE 8085

CMD ["uv", "run", "--no-sync", "uvicorn", "evidently_service.app:app", "--host", "0.0.0.0", "--port", "8085", "--workers", "1"]
