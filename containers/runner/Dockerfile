ARG OPENHANDS_BUILD_VERSION=dev

FROM python:3.12.3-slim AS backend-builder

WORKDIR /runner
ENV PYTHONPATH='/runner'

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

RUN apt-get update -y \
    && apt-get install -y curl make git build-essential \
    && python3 -m pip install poetry==1.8.2  --break-system-packages

COPY ./pyproject.toml ./poetry.lock ./
RUN touch README.md
RUN export POETRY_CACHE_DIR && poetry install --without evaluation,llama-index --no-root && rm -rf $POETRY_CACHE_DIR

FROM python:3.12.3-slim AS openhands-runner

WORKDIR /runner

ARG OPENHANDS_BUILD_VERSION #re-declare for this section

ENV RUN_AS_OPENHANDS=true
# A random number--we need this to be different from the user's UID on the host machine
ENV OPENHANDS_USER_ID=42420
ENV SANDBOX_LOCAL_RUNTIME_URL=http://host.docker.internal
ENV USE_HOST_NETWORK=false
ENV WORKSPACE_BASE=/opt/workspace_base
ENV OPENHANDS_BUILD_VERSION=$OPENHANDS_BUILD_VERSION
ENV SANDBOX_USER_ID=0
RUN mkdir -p $WORKSPACE_BASE

RUN apt-get update -y \
    && apt-get install -y curl ssh sudo

# Default is 1000, but OSX is often 501
RUN sed -i 's/^UID_MIN.*/UID_MIN 499/' /etc/login.defs
# Default is 60000, but we've seen up to 200000
RUN sed -i 's/^UID_MAX.*/UID_MAX 1000000/' /etc/login.defs

RUN groupadd runner
RUN useradd -l -m -u $OPENHANDS_USER_ID -s /bin/bash openhands && \
    usermod -aG runner openhands && \
    usermod -aG sudo openhands && \
    echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
RUN chown -R openhands:runner /runner && chmod -R 770 /runner
RUN sudo chown -R openhands:runner $WORKSPACE_BASE && sudo chmod -R 770 $WORKSPACE_BASE
USER openhands

ENV VIRTUAL_ENV=/runner/.venv \
    PATH="/runner/.venv/bin:$PATH" \
    PYTHONPATH='/runner'

COPY --chown=openhands:runner --chmod=770 --from=backend-builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

COPY --chown=openhands:runner --chmod=770 ./openhands ./openhands
COPY --chown=openhands:runner --chmod=777 ./openhands/runtime/plugins ./openhands/runtime/plugins
COPY --chown=openhands:runner --chmod=770 ./openhands/agenthub ./openhands/agenthub
COPY --chown=openhands:runner ./pyproject.toml ./pyproject.toml
COPY --chown=openhands:runner ./poetry.lock ./poetry.lock
COPY --chown=openhands:runner ./README.md ./README.md
COPY --chown=openhands:runner ./MANIFEST.in ./MANIFEST.in
COPY --chown=openhands:runner ./LICENSE ./LICENSE

# This is run as "openhands" user, and will create __pycache__ with openhands:openhands ownership
RUN python openhands/core/download.py # No-op to download assets
# Add this line to set group ownership of all files/directories not already in "runner" group
# openhands:openhands -> openhands:runner
RUN find /runner \! -group runner -exec chgrp runner {} +

USER root

WORKDIR /runner

CMD [ "sleep", "infinity" ]
