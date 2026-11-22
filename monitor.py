#!/usr/bin/env python3
"""Closed M5 London sweep and MSS alerts. Times on candles are UTC opens."""
import argparse
import json
import logging
import math
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
BUDAPEST = ZoneInfo("Europe/Budapest")
M5 = timedelta(minutes=5)
PIP = 0.0001
# The next open is already in the past at publication. Report only near-live
# confirmations and print the model open time explicitly.
MAX_AGE = 15
STATE = Path("london_alert_state.json")
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=5m&range=5d"


@dataclass(frozen=True)
class Bar:
    open_at: datetime
    high: float
    low: float
    close: float

    @property
    def end(self):
        return self.open_at + M5


@dataclass(frozen=True)
class Sweep:
    long: bool
    bar: Bar
    daily_level: float
    mss_level: float


def ny_time(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY).astimezone(UTC)


def day_bounds(day):
    previous = day - timedelta(days=3 if day.weekday() == 0 else 1)
    return ny_time(previous - timedelta(days=1), 17), ny_time(previous, 17)


def grid(start, end):
    return (start + i * M5 for i in range((end - start) // M5))


def swing_level(history, long):
    for index in range(len(history) - 3, 1, -1):
        group = history[index - 2:index + 3]
        if group[-1].open_at - group[0].open_at != 4 * M5:
            continue
        center = group[2]
        neighbors = group[:2] + group[3:]
        if long and all(center.high > bar.high for bar in neighbors):
            return center.high
        if not long and all(center.low < bar.low for bar in neighbors):
            return center.low
    return None


def replay(day, bars, as_of):
    """Return the day's first valid sweep and its MSS, if confirmed."""
    start, end = day_bounds(day)
    window = ny_time(day, 3)
    last_entry = ny_time(day, 3, 55)
    closed = {bar.open_at: bar for bar in bars if bar.end <= as_of}
    if any(stamp not in closed for stamp in grid(start, end)):
        return None, None, "incomplete_previous_day"
    previous = [closed[stamp] for stamp in grid(start, end)]
    high = max(bar.high for bar in previous)
    low = min(bar.low for bar in previous)
    history = sorted((bar for bar in closed.values() if start <= bar.open_at < window),
                     key=lambda bar: bar.open_at)
    sweep = None
    for stamp in grid(window, min(as_of, ny_time(day, 4))):
        bar = closed.get(stamp)
        if bar is None:
            return sweep, None, "missing_london_bar"
        if sweep is None:
            below, above = bar.low < low, bar.high > high
            if below and above:
                return None, None, "double_sweep"
            long = below and bar.close > low
            if long or (above and bar.close < high):
                level = swing_level(history, long)
                if level is None or (bar.close > level if long else bar.close < level):
                    return None, None, "invalid_sweep"
                sweep = Sweep(long, bar, low if long else high, level)
        else:
            touched_extreme = (bar.low <= sweep.bar.low if sweep.long
                               else bar.high >= sweep.bar.high)
            if touched_extreme:
                return sweep, None, "invalidated"
            if bar.end <= last_entry and (bar.close > sweep.mss_level if sweep.long else bar.close < sweep.mss_level):
                return sweep, bar, "mss"
        history.append(bar)
    return sweep, None, "expired" if as_of >= last_entry else "watching"


def get_bars():
    request = Request(YAHOO, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=4) as response:
        result = json.load(response)["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    rows = zip(result["timestamp"], quote["high"], quote["low"], quote["close"], strict=True)
    bars = []
    for stamp, high, low, close in rows:
        if stamp % 300 == 0 and all(v is not None and math.isfinite(v) and v > 0
                                    for v in (high, low, close)) and low <= close <= high:
            bars.append(Bar(datetime.fromtimestamp(stamp, UTC), high, low, close))
    # Require a subsequent timestamp so a stale cached, still-forming last bar
    # cannot turn into a signal merely because local wall time moved forward.
    return bars[:-1]


def publish(title, message):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    server = os.environ.get("NTFY_SERVER", "").rstrip("/") or "https://ntfy.sh"
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,100}", topic) or urlparse(server).scheme != "https":
        raise RuntimeError("Invalid ntfy settings")
    headers = {"Title": title, "Content-Type": "text/plain; charset=utf-8"}
    if token := os.environ.get("NTFY_TOKEN"):
        headers["Authorization"] = "Bearer " + token
    request = Request(f"{server}/{topic}", data=message.encode(), headers=headers)
    with urlopen(request, timeout=5) as response:
        event = json.load(response)
        if event.get("event") != "message" or not event.get("id"):
            raise RuntimeError("Missing ntfy publication acknowledgement")
        logging.info("ntfy accepted title=%s HTTP=%s id=%s", title, response.status, event["id"])


def hun(stamp):
    return stamp.astimezone(BUDAPEST).strftime("%Y-%m-%d %H:%M %Z")


def claim(key, persist):
    state = json.loads(STATE.read_text()) if STATE.exists() else []
    if key in state:
        return False
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps([*state[-29:], key], indent=2) + "\n")
    tmp.replace(STATE)
    persist()
    return True


def persist_git():
    subprocess.run(["git", "add", str(STATE)], check=True)
    subprocess.run(["git", "commit", "-m", "Reserve London ntfy notification"], check=True)
    subprocess.run(["git", "push", "origin", "HEAD:main"], check=True, timeout=10)


def send(day, kind, event_time, observed, title, message, persist):
    age = (observed - event_time).total_seconds()
    if not 0 <= age <= MAX_AGE:
        logging.info("Late %s suppressed, source delay=%.2fs", kind, age)
        return
    if claim(f"{day}:{kind}", persist):
        elapsed = (datetime.now(UTC) - event_time).total_seconds()
        if elapsed > MAX_AGE:
            logging.info("Late %s suppressed after state reservation, delay=%.2fs", kind, elapsed)
            return
        publish(title, message)
        logging.info("%s source delay=%.2fs, signal to ntfy acceptance=%.2fs",
                     kind, age, (datetime.now(UTC) - event_time).total_seconds())


def notify_events(day, sweep, mss, observed, persist):
    direction = "LONG" if sweep.long else "SHORT"
    extreme = sweep.bar.low if sweep.long else sweep.bar.high
    deadline = ny_time(day, 3, 55)
    if observed < deadline:
        send(day, "sweep", sweep.bar.end, observed, f"EUR/USD {direction} sweep - MSS meg nincs",
             f"Irány: {direction}\nElőző napi áttört szint: {sweep.daily_level:.5f}\n"
             f"Sweep szélsőértéke: {extreme:.5f}\nFigyelt MSS: {sweep.mss_level:.5f}\n"
             f"Utolsó modellbelépés: {hun(deadline)}", persist)
    if mss:
        stop = extreme - PIP if sweep.long else extreme + PIP
        formula = "E + 2 × (E − stop)" if sweep.long else "E − 2 × (stop − E)"
        send(day, "mss", mss.end, observed, f"EUR/USD {direction} MSS megerositve",
             f"Irány: {direction}\nMSS-szint: {sweep.mss_level:.5f}\n"
             f"Zárás: {mss.close:.5f} | {hun(mss.end)}\n"
             f"Modellbelépés: {hun(mss.end)}, a következő gyertya nyitása\n"
             f"Modellstop: {stop:.5f}\n2R cél: {formula}, ahol E a tényleges belépőár.", persist)


def watch():
    now = datetime.now(UTC)
    day = now.astimezone(NY).date()
    first_close = ny_time(day, 3, 5)
    finish = ny_time(day, 4) + timedelta(seconds=MAX_AGE)
    if day.weekday() >= 5 or now < ny_time(day, 2, 44) or now > finish:
        return
    latest = None
    last_probe = None
    while datetime.now(UTC) <= finish:
        now = datetime.now(UTC)
        boundary = max(first_close, datetime.fromtimestamp(int(now.timestamp()) // 300 * 300, UTC))
        age = (now - boundary).total_seconds()
        probe_slot = sum(age >= offset for offset in (0, 25, 55, 115))
        if now < boundary or latest == boundary:
            next_poll = boundary if now < boundary else boundary + M5
            if next_poll > finish:
                break
            time.sleep(min(30, max(0, (next_poll - now).total_seconds())))
            continue
        if age > MAX_AGE and last_probe == (boundary, probe_slot):
            time.sleep(1)
            continue
        last_probe = boundary, probe_slot
        try:
            bars = get_bars()
        except (OSError, KeyError, IndexError, ValueError) as exc:
            logging.warning("Yahoo M5 failed: %s HTTP=%s", type(exc).__name__, getattr(exc, "code", "-"))
            time.sleep(3)
            continue
        observed = datetime.now(UTC)
        last = max((bar.end for bar in bars if bar.end <= observed), default=None)
        logging.info("Yahoo latest closed=%s age_seconds=%s", last,
                     (observed - last).total_seconds() if last else None)
        if last and last >= boundary:
            latest = boundary
            sweep, mss, status = replay(day, bars, observed)
            logging.info("Replay %s status=%s", day, status)
            if sweep is not None and status not in {"invalidated", "missing_london_bar"}:
                notify_events(day, sweep, mss, observed, persist_git)
        else:
            time.sleep(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("test-ntfy", "probe", "watch"))
    mode = parser.parse_args().mode
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if mode == "test-ntfy":
        publish("TESZT - EUR/USD London sweep + MSS", "Kapcsolatteszt az új monitorból.")
    elif mode == "probe":
        bars = get_bars()
        logging.info("Yahoo M5 rows=%s last_closed=%s", len(bars), bars[-1].end if bars else None)
    else:
        watch()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # urllib errors can contain the private topic in their URL.
        logging.error("Monitor failed: %s HTTP=%s", type(exc).__name__, getattr(exc, "code", "-"))
        raise SystemExit(1) from None
