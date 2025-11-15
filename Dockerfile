FROM python:3.13-alpine

ENV FLASK_APP llm-api-connector.py
ENV FLASK_CONFIG production

RUN adduser -D flasky
USER flasky

WORKDIR /home/flasky

COPY requirements requirements
RUN python -m venv venv
RUN venv/bin/pip install -r requirements/docker.txt

COPY app app
# COPY migrations migrations
COPY llm-api-connector.py config.py boot.sh ./

RUN ls -ltra
RUN chmod 0750 boot.sh

# run-time configuration
EXPOSE 5000
ENTRYPOINT ["./boot.sh"]