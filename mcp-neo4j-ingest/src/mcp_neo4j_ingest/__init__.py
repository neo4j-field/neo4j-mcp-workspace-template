def main():
    """Start the server without importing database dependencies for library use."""

    from .server import main as run_server

    return run_server()
