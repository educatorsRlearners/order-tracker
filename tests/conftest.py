import os

# Console exporters flush at interpreter exit, after pytest has closed its captured stdout.
os.environ.setdefault("ORDER_TRACKER_TELEMETRY", "off")
