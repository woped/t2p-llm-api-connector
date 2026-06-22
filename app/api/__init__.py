from flask import Blueprint

bp = Blueprint("api", __name__)

# Imported for its side effect: registers the route handlers on `bp`. Must come
# after `bp` is defined, hence the late import.
from app.api import routes  # noqa: E402,F401
