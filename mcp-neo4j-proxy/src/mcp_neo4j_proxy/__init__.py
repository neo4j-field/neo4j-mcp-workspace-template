def main():
    """Start the proxy without importing its server during library-only use."""
    from .server import main as run_server

    return run_server()
