"""Dumps the readings table to a .xlsx file. SQLite is the source of truth;
this is a derived, regenerate-from-scratch artifact - never written to
directly on every telemetry POST."""
import logging
import os

from openpyxl import Workbook
from sqlmodel import Session, select

from models import ReadingRow

logger = logging.getLogger("excel_export")

EXPORT_PATH = os.getenv("EXPORT_PATH", "data/readings_export.xlsx")

_HEADERS = [
    "timestamp",
    "temp_c",
    "humidity",
    "soil_moisture",
    "reported_relay_state",
    "commanded_relay_state",
    "mode",
]


def export_readings_to_excel(session: Session, path: str = EXPORT_PATH) -> int:
    """Writes every row in the readings table to `path`. Returns row count."""
    rows = session.exec(select(ReadingRow).order_by(ReadingRow.timestamp)).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "readings"
    ws.append(_HEADERS)

    for row in rows:
        ws.append(
            [
                row.timestamp.isoformat(),
                row.temp_c,
                row.humidity,
                row.soil_moisture,
                row.reported_relay_state,
                row.commanded_relay_state,
                row.mode,
            ]
        )

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    wb.save(path)
    logger.info("Exported %d readings to %s", len(rows), path)
    return len(rows)
