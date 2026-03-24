"""Entrypoint shim for bot-metrics-exporter Docker service."""

from services.bot_metrics_exporter import main

if __name__ == "__main__":
    main()
