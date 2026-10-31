"""Strukturierte Logs: eine JSON-Zeile pro Ereignis auf stderr."""

import json
import logging
import sys

_STD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # alles aus extra={...} landet als eigenes Feld im JSON
        data |= {k: v for k, v in vars(record).items() if k not in _STD}
        return json.dumps(data, default=str)


def setup(verbose: bool = False) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    logging.getLogger("llmctl").setLevel(logging.DEBUG if verbose else logging.INFO)
    if verbose:
        logging.getLogger("httpx").setLevel(logging.INFO)
