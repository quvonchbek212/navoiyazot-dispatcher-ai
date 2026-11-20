"""Compact full-history stream: one vehicle in memory, no row-count truncation."""
from datetime import datetime, timedelta, timezone

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class StreamingHistory:
    def __init__(self, packets):
        self._packets = iter(packets)
        self._next = None
        self._started = False
        self._last_id = None
        self.rows_read = 0
        self.distinct_rows_read = 0
        self.complete = False
        self.cancelled = None

    def _advance(self):
        if self.cancelled is not None and self.cancelled.is_set():
            raise InterruptedError("Monitoring request cancelled")
        try:
            self._next = next(self._packets)
        except StopIteration:
            self._next = None
            self.complete = True

    def get(self, vehicle_id, default=None):
        if self._last_id is not None and vehicle_id <= self._last_id:
            raise ValueError("GPS history must be consumed once in vehicle ID order")
        self._last_id = vehicle_id
        if not self._started:
            self._started = True
            self._advance()
        groups = {}
        while self._next is not None and self._next["vehicle_id"] <= vehicle_id:
            packet = self._next
            if packet["vehicle_id"] != vehicle_id:
                raise ValueError("GPS stream contains an unexpected vehicle")
            rows = groups.setdefault(packet["source"], [])
            for us, lat, lon, valid, speed, unit, engine, copies in packet["points"]:
                self.rows_read += copies
                self.distinct_rows_read += 1
                rows.append({"timestamp": EPOCH + timedelta(microseconds=int(us)),
                    "latitude": lat, "longitude": lon, "valid": valid,
                    "speed_kph": speed if unit else None, "engine_on": engine,
                    "_speed_unit": unit, "_copies": copies})
            self._advance()
        return groups or default or {}

    def close(self):
        close = getattr(self._packets, "close", None)
        if close:
            close()
