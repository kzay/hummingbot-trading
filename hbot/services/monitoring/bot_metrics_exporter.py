import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bot_metrics_exporter import main  # noqa: E402

if __name__ == "__main__":
    main()
