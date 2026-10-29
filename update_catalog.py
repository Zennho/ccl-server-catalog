#!/usr/bin/env python3
"""Build a daily, deduplicated snapshot from public Java server directories."""
import concurrent.futures
import datetime as dt
import ipaddress
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "data" / "servers.json"
USER_AGENT = "CCL-Server-Catalog/0.2 (+https://github.com/Zennho/ccl-server-catalog)"
SOURCES = {
    "minecraft-java-servers": ("Minecraft Java Servers", "https://minecraft-java-servers.com/"),
    "minecraftservers": ("minecraftservers", "https://minecraftserve.rs/"),
    "mcsrvlist": ("MCSrvList", "https://mcsrvlist.com/"),
    "msid": ("minecraftserver.id", "https://minecraftserver.id/"),
    "anyserver": ("AnyServer", "https://anyserver.pro/"),
    "cloudclient": ("Cloud Client", "https://cloudclient.gg/"),
    "msl": ("MC Server List", "https://msl.appahouse.com/"),
}


def text(value, limit=160):
    value = str(value or "").encode("utf-8", "replace").decode("utf-8")
    return re.sub(r"\s+", " ", value).strip()[:limit]


def host_address(host, port):
    host = text(host, 280).lower().rstrip(".")
    if port is None:
        port = 25565
    bracketed = re.fullmatch(r"\[([0-9a-f:.]+)\](?::([0-9]+))?", host)
    if bracketed:
        host = bracketed.group(1)
        if bracketed.group(2):
            port = bracketed.group(2)
    elif host.count(":") == 1:
        hostname, embedded = host.rsplit(":", 1)
        if embedded.isdigit():
            host, port = hostname.rstrip("."), embedded
    if not host or len(host) > 253 or isinstance(port, bool):
        return None
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None
    if not 1 <= port <= 65535:
        return None
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
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


def normalize(entry, source="minecraft-java-servers"):
    if not isinstance(entry, dict):
        return None
    if source in ("minecraft-java-servers", "minecraftservers", "mcsrvlist", "cloudclient"):
        host = entry.get("host") if source != "cloudclient" else entry.get("address")
    elif source == "msl":
        host = entry.get("ipAddress")
    else:
        host = entry.get("address")
    address = host_address(host, entry.get("port", 25565))
    if not address:
        return None
    tags = entry.get("types") if source == "minecraft-java-servers" else entry.get("modes") if source == "mcsrvlist" else entry.get("gameModes") if source == "msl" else entry.get("category") if source == "anyserver" else entry.get("tags")
    if isinstance(tags, str):
        tags = tags.split(",")
    tags = [text(tag, 30) for tag in tags[:8] if isinstance(tag, str) and text(tag, 30)] if isinstance(tags, list) else []
    description = entry.get("short_description") if source == "minecraft-java-servers" else entry.get("tagline") if source in ("minecraftservers", "mcsrvlist") else entry.get("server_summary") if source == "anyserver" else entry.get("motd") if source == "cloudclient" else entry.get("description")
    status = entry.get("status") if source in ("minecraft-java-servers", "msid") else entry.get("is_online") if source == "anyserver" else entry.get("isOnline") if source == "msl" else entry.get("online")
    if source == "anyserver" and type(status) is int:
        status = bool(status) if status in (0, 1) else None
    status = status.lower() if isinstance(status, str) else "online" if status is True else "offline" if status is False else "unknown"
    if status not in ("online", "offline"):
        status = "unknown"
    players = entry.get("players") if source == "minecraftservers" and isinstance(entry.get("players"), dict) else {}
    online = entry.get("players_online") if source == "minecraft-java-servers" else players.get("online") if source == "minecraftservers" else entry.get("players") if source == "mcsrvlist" else entry.get("currentPlayers") if source in ("msid", "msl") else entry.get("player_count") if source == "anyserver" else entry.get("playersOnline")
    maximum = entry.get("players_total") if source == "minecraft-java-servers" else players.get("max") if source == "minecraftservers" else entry.get("maxPlayers") if source in ("mcsrvlist", "msid", "msl") else entry.get("max_players") if source == "anyserver" else entry.get("playersMax")
    return {
        "name": text(entry.get("name"), 100) or address,
        "address": address,
        "description": text(description, 220),
        "version": text(entry.get("minecraftVersion") if source == "msl" else entry.get("version"), 100),
        "status": status,
        "playersOnline": nonnegative(online),
        "playersMax": nonnegative(maximum),
        "tags": tags,
        "requiresMods": entry.get("requires_mods") if source == "minecraft-java-servers" and type(entry.get("requires_mods")) is bool else None,
        "sourceIds": [source],
    }


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(8_000_001)
                if len(body) > 8_000_000:
                    raise ValueError("API response too large")
                data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("Unexpected API response")
            return data
        except (OSError, ValueError) as error:
            if attempt == 2:
                raise RuntimeError(f"Request failed: {type(error).__name__}") from error
            delay = 2 ** attempt
            if isinstance(error, urllib.error.HTTPError) and error.code == 429:
                try:
                    delay = min(60, max(delay, int(error.headers.get("Retry-After", delay))))
                except (TypeError, ValueError):
                    pass
            time.sleep(delay)


def pages(url, rows, pagination, cap):
    result = []
    total_pages = None
    for page in range(1, cap + 1):
        data = fetch_json(url(page))
        items = rows(data)
        if not isinstance(items, list):
            raise ValueError("Invalid server list")
        if total_pages is None:
            total_pages = pagination(data)
            if type(total_pages) is not int or total_pages < 0 or total_pages > 1_000_000:
                raise ValueError("Invalid pagination")
        if not items and page < total_pages:
            raise ValueError("Unexpected empty page")
        result.extend(items)
        if page >= total_pages:
            break
        time.sleep(1.2)
    return result, total_pages > cap


def total_pages(total, size):
    if type(total) is not int or total < 0 or total > 50_000_000:
        raise ValueError("Invalid total count")
    return (total + size - 1) // size


def fetch_source(source):
    if source == "minecraft-java-servers":
        return pages(lambda p: f"https://minecraft-java-servers.com/api/v1/servers?per_page=500&page={p}", lambda d: d.get("data"), lambda d: int(d.get("meta", {}).get("total_pages", -1)), 40)
    if source == "minecraftservers":
        return pages(lambda p: f"https://minecraftserve.rs/api/servers?edition=java&per=50&page={p}", lambda d: d.get("servers"), lambda d: int(d.get("pages", -1)), 500)
    if source == "mcsrvlist":
        return pages(lambda p: f"https://mcsrvlist.com/api/servers?edition=java&limit=50&page={p}", lambda d: d.get("items"), lambda d: int(d.get("pages", -1)), 500)
    if source == "msid":
        all_items, truncated = [], False
        for edition in ("JAVA", "CROSS_PLAY"):
            items, limited = pages(lambda p: f"https://api.minecraftserver.id/api/v1/public/servers?edition={edition}&limit=50&page={p}", lambda d: d.get("data", {}).get("servers"), lambda d: int(d.get("data", {}).get("totalPages", -1)), 500)
            all_items.extend(items)
            truncated |= limited
            time.sleep(1.2)
        return all_items, truncated
    if source == "anyserver":
        return pages(lambda p: f"https://anyserver.pro/api/servers?game=mc_java&limit=100&offset={(p-1)*100}", lambda d: d.get("servers"), lambda d: total_pages(d.get("total"), 100), 500)
    if source == "cloudclient":
        return pages(lambda p: f"https://api.cloudclient.gg/v1/mclist?perPage=50&page={p}", lambda d: d.get("items"), lambda d: total_pages(d.get("total"), 50), 500)
    if source == "msl":
        return pages(lambda p: f"https://msl.appahouse.com/api/servers?limit=100&offset={(p-1)*100}", lambda d: d.get("servers"), lambda d: int(d.get("pagination", {}).get("totalPages", -1)), 500)
    raise ValueError("Unknown source")


def previous_snapshot():
    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("servers"), list) else {}
    except (OSError, ValueError):
        return {}


def merge(ordered):
    entries = {}
    for source, rows in ordered:
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("address"), str):
                continue
            old = entries.get(row["address"])
            if old is None:
                copy = dict(row)
                copy["sourceIds"] = [source]
                entries[row["address"]] = copy
            else:
                if source not in old["sourceIds"]:
                    old["sourceIds"].append(source)
                for key in ("description", "version"):
                    if not old.get(key) and row.get(key):
                        old[key] = row[key]
                if old.get("status") == "unknown" and row.get("status") in ("online", "offline"):
                    old["status"] = row["status"]
                for key in ("playersOnline", "playersMax", "requiresMods"):
                    if old.get(key) is None and row.get(key) is not None:
                        old[key] = row[key]
                old["tags"] = list(dict.fromkeys(old.get("tags", []) + row.get("tags", [])))[:8]
    # Attribution is part of the visible description for older launchers that
    # predate sourceIds. New launchers also display the source list and links.
    suffix = " · 来源 minecraftserver.id"
    for row in entries.values():
        if "msid" in row["sourceIds"] and not row["description"].endswith(suffix):
            row["description"] = row["description"][:220-len(suffix)].rstrip() + suffix
    return list(entries.values())


def update():
    old = previous_snapshot()
    old_sources = {s.get("id"): s for s in old.get("sources", []) if isinstance(s, dict)}
    ordered, source_meta = [], []
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    success = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        futures = {source: pool.submit(fetch_source, source) for source in SOURCES}
        results = {}
        for source, future in futures.items():
            try:
                results[source] = (future.result(), None)
            except Exception as error:
                results[source] = (None, error)
    for source, (name, url) in SOURCES.items():
        try:
            result, error = results[source]
            if error:
                raise error
            raw, truncated = result
            normalized = [item for row in raw if (item := normalize(row, source)) is not None]
            if raw and not normalized:
                raise ValueError("No valid Java server addresses")
            ordered.append((source, normalized))
            source_meta.append({"id": source, "name": name, "url": url, "updatedAt": now, "status": "ok", "count": len(normalized), "truncated": truncated})
            success += 1
            print(f"{name}: {len(normalized)} servers; truncated={truncated}")
        except Exception as error:
            retained = [row for row in old.get("servers", []) if isinstance(row, dict) and source in row.get("sourceIds", ["minecraft-java-servers"])]
            ordered.append((source, retained))
            info = old_sources.get(source, {})
            source_meta.append({"id": source, "name": name, "url": url, "updatedAt": info.get("updatedAt", old.get("updatedAt") if retained else None), "status": "stale" if retained else "unavailable", "count": len(retained), "truncated": bool(info.get("truncated", False))})
            print(f"{name}: unavailable ({type(error).__name__}); retained {len(retained)}", file=sys.stderr)
    servers = merge(ordered)
    if not success or not servers:
        raise RuntimeError("No source succeeded or no valid servers returned; preserving previous snapshot")
    snapshot = {"schemaVersion": 1, "updatedAt": now, "source": {"name": "多来源公开服务器目录", "url": "https://github.com/Zennho/ccl-server-catalog"}, "sources": source_meta, "truncated": any(s["truncated"] for s in source_meta), "servers": servers}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(tmp, OUT)
    print(f"Saved {len(servers)} unique servers to {OUT}")


if __name__ == "__main__":
    try:
        update()
    except Exception as error:
        print(f"Catalogue update failed: {error}", file=sys.stderr)
        sys.exit(1)
