"""MCP Neo4j Lexical Graph Server.

Creates rich lexical graphs from PDF documents in Neo4j.
Supports multiple parse modes, pluggable chunking, and document versioning.
"""

from .server import run as main

__all__ = ["main"]
