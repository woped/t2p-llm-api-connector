from flask import Blueprint

from app.api import routes  # noqa: F401

bp = Blueprint("api", __name__)
