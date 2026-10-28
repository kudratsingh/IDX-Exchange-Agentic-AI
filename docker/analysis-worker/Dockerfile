# WO-017 analysis worker (ADR-0013). Build once per machine and pin the image ID:
# see README.md. A user turn never builds or pulls this image.
FROM python:3.11-slim@sha256:ae952e0a57138a4317b9b61caaa19a8217c2f356803f8d7e63aad08769950937

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt /opt/worker/requirements.txt
# Optional build secret `pip_cert`: a CA bundle for a TLS-inspecting proxy on the
# build machine. It is mounted for this step only and never stored in a layer.
RUN --mount=type=secret,id=pip_cert,required=false \
    if [ -s /run/secrets/pip_cert ]; then export PIP_CERT=/run/secrets/pip_cert; fi \
    && pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: \
        -r /opt/worker/requirements.txt

COPY bootstrap.py render.py /opt/worker/

# Build matplotlib's font list once, into a root-owned read-only directory. At run
# time the worker copies it into the writable tmpfs (MPLCONFIGDIR) before use.
RUN MPLCONFIGDIR=/opt/mpl-cache MPLBACKEND=Agg \
        python -c "import matplotlib.font_manager" \
    && chown -R root:root /opt/worker /opt/mpl-cache \
    && chmod -R u=rwX,go=rX /opt/worker /opt/mpl-cache

# The run's PID 1: a copy of coreutils `timeout` that kills the worker a few seconds
# after the host's wall clock even if the host process is gone. Mode 0711 lets the
# worker user execute it but not read it, so with --cap-drop ALL the kernel marks it
# non-dumpable and model code running as the same user cannot ptrace it. As the
# namespace's init it also ignores SIGKILL and SIGSTOP sent from inside.
RUN install -o root -g root -m 0711 /usr/bin/timeout /opt/worker/deadline

ENV MPLCONFIGDIR=/tmp/matplotlib \
    MPLBACKEND=Agg

USER 65534:65534
WORKDIR /tmp
