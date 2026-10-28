#!/usr/bin/env python3
"""Refresh CCL's public Java server catalogue from a documented public API."""
import datetime as dt
import ipaddress
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

API = "https://minecraft-java-servers.com/api/v1/servers?per_page=500&page={}"
SOURCE = "https://minecraft-java-servers.com/"
MAX_PAGES = 5
OUT = Path(__file__).parent / "data" / "servers.json"


def text(value, limit=160):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def host_address(host, port):
    host = text(host, 253).lower().rstrip(".")
    if not host or isinstance(port, bool):
        return None
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None
    if not 1 <= port <= 65535:
        return None
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        # Omit literal private addresses; hostnames may still resolve differently.
        if not ip.is_global:
            return None
        host = f"[{ip}]" if ip.version == 6 else str(ip)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host):
            return None
        if any(not label or label.startswith("-") or label.endswith("-") or len(label) > 63 for label in host.split(".")):
            return None
        if "." not in host:
            return None
    return host if port == 25565 else f"{host}:{port}"


def nonnegative(value):
    return value if type(value) is int and 0 <= value <= 10_000_000 else None


def normalize(entry):
    if not isinstance(entry, dict):
        return None
    address = host_address(entry.get("host"), entry.get("port", 25565))
    if not address:
        return None
    tags = entry.get("types")
    tags = [text(tag, 30) for tag in tags[:8] if isinstance(tag, str) and text(tag, 30)] if isinstance(tags, list) else []
    return {
        "name": text(entry.get("name"), 100) or address,
        "address": address,
        "description": text(entry.get("short_description"), 220),
        "version": text(entry.get("version"), 100),
        "status": entry.get("status") if entry.get("status") in ("online", "offline") else "unknown",
        "playersOnline": nonnegative(entry.get("players_online")),
        "playersMax": nonnegative(entry.get("players_total")),
        "tags": tags,
        "requiresMods": entry.get("requires_mods") if type(entry.get("requires_mods")) is bool else None,
    }


def fetch_page(page):
    request = urllib.request.Request(API.format(page), headers={"User-Agent": "CCL-Server-Catalog/0.1 (+https://github.com/Zennho/ccl-server-catalog)", "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(8_000_001)
                if len(body) > 8_000_000:
                    raise ValueError("API response too large")
                data = json.loads(body)
            if not isinstance(data.get("data"), list) or not isinstance(data.get("meta"), dict):
                raise ValueError("Unexpected API response")
            return data
        except (OSError, ValueError) as error:
            if attempt == 2:
                raise RuntimeError(f"Page {page} failed: {error}") from error
            time.sleep(2 ** attempt)


def update():
    servers = []
    seen = set()
    total_pages = None
    for page in range(1, MAX_PAGES + 1):
        response = fetch_page(page)
        if total_pages is None:
            total_pages = int(response["meta"].get("total_pages", 1))
        for item in response["data"]:
            server = normalize(item)
            if server and server["address"] not in seen:
                seen.add(server["address"])
                servers.append(server)
        if page >= total_pages:
            break
        time.sleep(1)
    if not servers:
        raise RuntimeError("No valid servers returned; preserving previous snapshot")
    snapshot = {
        "schemaVersion": 1,
        "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": {"name": "Minecraft Java Servers", "url": SOURCE},
        "truncated": total_pages > MAX_PAGES,
        "servers": servers,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, OUT)
    print(f"Saved {len(servers)} servers to {OUT}; truncated={snapshot['truncated']}")


if __name__ == "__main__":
    try:
        update()
    except Exception as error:
        print(f"Catalogue update failed: {error}", file=sys.stderr)
        sys.exit(1)
