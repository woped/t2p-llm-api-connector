#!/bin/sh
# POSIX `.` (not the bash-only `source`) since the shebang is /bin/sh.
. venv/bin/activate

exec gunicorn -b :5000 --access-logfile - --error-logfile - llm-api-connector:app