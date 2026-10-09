# One parameterized image definition for every Python service (DRY).
# Build context: repository root.  Usage: --build-arg SERVICE=race_engine

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS build
ARG SERVICE
RUN python -m venv /opt/venv
COPY libs/common /src/libs/common
COPY services/${SERVICE} /src/services/${SERVICE}
RUN /opt/venv/bin/pip install /src/libs/common /src/services/${SERVICE}

FROM base AS runtime
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
 && mkdir -p /data \
 && chown app:app /data
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /app
USER app
