#!/bin/sh
. venv/bin/activate

# Schemamigration of flask
# while true; do
#     flask deploy
#     if [[ "$?" == "0" ]]; then
#         break
#     fi
#     echo Deploy command failed, retrying in 5 secs...
#     sleep 5
# done

exec venv/bin/gunicorn -b :5000 --access-logfile - --error-logfile - llm-api-connector:app