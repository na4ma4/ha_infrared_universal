FROM python:3.14.2-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*
