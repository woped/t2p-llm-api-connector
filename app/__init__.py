from flask import Flask
from config import get_config
import click
import unittest
import sys


def create_app(config_class=None):
    """Application factory pattern"""
    app = Flask(__name__)
    
    # Load configuration
    if config_class is None:
        config_class = get_config()
    app.config.from_object(config_class)
    
    # Register blueprints
    from app.api import bp as api_bp
    app.register_blueprint(api_bp)
    
    # CLI Commands
    @app.cli.command("test")
    def test():
        """Run the unit tests."""
        loader = unittest.TestLoader()
        start_dir = 'tests'
        suite = loader.discover(start_dir)
        
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        
        if result.wasSuccessful():
            return 0
        sys.exit(1)
    
    return app
