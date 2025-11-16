FROM python:3.13-alpine

# Runtime environment for production
ENV FLASK_APP=llm-api-connector.py \
    FLASK_ENV=production \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# User + Gruppe anlegen
RUN addgroup -S flasky && adduser -S -G flasky flasky

WORKDIR /home/flasky

# Requirements kopieren + installieren (als root)
COPY requirements requirements
RUN python -m venv venv && venv/bin/pip install -r requirements/docker.txt

# App-Dateien kopieren (mit Ownership direkt setzen)
COPY --chown=flasky:flasky app app
COPY --chown=flasky:flasky llm-api-connector.py config.py boot.sh ./

# Rechte setzen (noch root, oder direkt per COPY + Ausführbit gesetzt)
RUN chmod 0750 boot.sh

# Optional: prüfen
# RUN ls -l boot.sh

# Wechsel zu nicht-root
USER flasky

EXPOSE 5000
ENTRYPOINT ["./boot.sh"]