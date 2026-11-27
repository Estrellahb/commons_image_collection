FROM python:3.12.14-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 MPLBACKEND=Agg \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 MPLCONFIGDIR=/tmp/matplotlib

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=2 update && apt-get install -y --no-install-recommends \
    ca-certificates curl ffmpeg tesseract-ocr tesseract-ocr-eng \
    poppler-utils fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
ARG REQUIREMENTS_FILE=requirements.lock.txt
COPY ${REQUIREMENTS_FILE} /opt/zerobench/requirements.txt
RUN pip install --no-cache-dir -r /opt/zerobench/requirements.txt \
    && pip freeze > /opt/zerobench/requirements.lock.txt

WORKDIR /workspace
CMD ["sleep", "infinity"]
