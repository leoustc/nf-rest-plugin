FROM ubuntu:22.04 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UVICORN_WORKERS=1

# System tooling + Miniforge (conda from conda-forge)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates wget bzip2 ssh awscli tree vim && \
    rm -rf /var/lib/apt/lists/*

RUN wget -qO /tmp/miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh && \
    bash /tmp/miniforge.sh -b -p /opt/conda && \
    rm /tmp/miniforge.sh && \
    /opt/conda/bin/conda config --system --set channel_priority strict && \
    /opt/conda/bin/conda install -y python=3.11 conda-forge::terraform conda-forge::oci-cli && \
    /opt/conda/bin/conda clean -afy

ENV PATH=/opt/conda/bin:$PATH

RUN pip install --no-cache-dir fastapi uvicorn[standard] pymysql cryptography ansible

WORKDIR /app

FROM base AS runtime

WORKDIR /app

COPY . .

# Add entry script
RUN chmod +x /app/entry.sh

EXPOSE 8080

ENTRYPOINT ["/app/entry.sh"]
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port 8080 --workers ${UVICORN_WORKERS:-2} --log-level error"]