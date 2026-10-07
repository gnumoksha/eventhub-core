#|
#| References
#|
# https://github.com/astral-sh/uv-docker-example/blob/00701a3361b9bdc896f8549fb9f890f99d115824/Dockerfile
# https://github.com/astral-sh/uv-docker-example/blob/00701a3361b9bdc896f8549fb9f890f99d115824/multistage.Dockerfile

#|
#| Base image
#|
FROM python:3.14 AS base

RUN set -eux; \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    git  \
    openssh-client \
    python3-dev \
    libpq-dev \
    build-essential \
    pkg-config \
    antiword \
    ; \
    apt-get dist-clean

# Setup a non-root user
RUN groupadd --system --gid 999 app \
    && useradd --system --gid 999 --uid 999 --create-home app

# Disable Python downloads, because we want to use the system interpreter
# across images.
ENV UV_PYTHON_DOWNLOADS=0

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

EXPOSE 8000

#|
#| Production image
#|
FROM base AS production

# Omit development dependencies
ENV UV_NO_DEV=1

RUN mkdir -p -m 0700 /root/.ssh \
    && ssh-keyscan -H github.com >> /root/.ssh/known_hosts \
    && chmod 644 /root/.ssh/known_hosts

# In the reference the following was used to install the dependencies before
# copying the entire source code. Here it is not possible because uv complains
# about the missing packages/ directory.
# --no-sources didn't work.
# RUN --mount=type=cache,target=/root/.cache/uv \
#     --mount=type=bind,source=uv.lock,target=uv.lock \
#     --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
#     uv sync --locked --no-install-project
# COPY . /app

COPY ./pyproject.toml /app/pyproject.toml
COPY ./uv.lock /app/uv.lock
COPY ./src /app/src
COPY ./packages /app/packages
COPY ./migrations /app/migrations
COPY ./alembic.ini /app/alembic.ini
# uv complains about the missing README.md
COPY ./README.md /app/README.md

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=ssh \
    uv sync --locked

ARG APP_VERSION
ENV APP_VERSION=$APP_VERSION
# It isn't possible to optimize at this level because we need the
# comments in the code.
#ENV PYTHONOPTIMIZE=2

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Remove uv as it shouldn't be necessary on production.
# RUN rm /bin/uv /bin/uvx

CMD ["fastapi", "run", "src/eventhub_core/main.py", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--root-path", "/eventhub"]
