#!/usr/bin/env python3
import html
import json
import re
import sys
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

PAGE = "https://www.vpnbook.com/freevpn/openvpn"
API = "https://www.vpnbook.com/api/openvpn"
OUT = Path("public/servers.json")
USER = "vpnbook"
HEADERS = {"User-Agent": "Setup-VPN-VPNBook-Updater/2.0"}
COUNTRIES = {
    "us": "United States",
    "ca": "Canada",
    "uk": "United Kingdom",
    "de": "Germany",
    "fr": "France",
}
PROTOCOLS = {
    "tcp443": ("TCP", 443),
    "tcp80": ("TCP", 80),
    "udp53": ("UDP", 53),
    "udp25000": ("UDP", 25000),
}


def get(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def plain_html(page):
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def valid_password(value):
    return bool(re.fullmatch(r"[A-Za-z0-9]{5,32}", value)) and value.lower() != USER


def parse_password(page):
    plain = " ".join(plain_html(page).split())
    match = re.search(r"\bPassword\b\s*(?:[:=\-]\s*)?([A-Za-z0-9]{5,32})\b", plain, re.I)
    if not match or not valid_password(match.group(1)):
        raise RuntimeError("VPNBook password was not found or failed validation")
    return match.group(1)


def parse_updated_at(page):
    plain = " ".join(plain_html(page).split())
    match = re.search(r"Last updated:\s*([^|]+?)(?:\s+Support VPNBook|\s*$)", plain, re.I)
    return match.group(1).strip() if match else ""


def parse_servers(page):
    seen = set()
    counters = {}
    servers = []
    pattern = re.compile(r"\b([a-z]{2})(\d+)\.vpnbook\.com\b", re.I)

    for match in pattern.finditer(page):
        code = match.group(1).lower()
        host = match.group(0).lower()
        if code not in COUNTRIES or host in seen:
            continue
        seen.add(host)
        counters[code] = counters.get(code, 0) + 1
        servers.append({
            "id": host,
            "country": COUNTRIES[code],
            "name": f"{code.upper()} Server {counters[code]}",
            "host": host,
            "status": "ONLINE",
            "ping": None,
        })

    if not servers:
        raise RuntimeError("No OpenVPN servers found on VPNBook page")
    return servers


def fetch_config(host, protocol):
    url = f"{API}?hostname={urllib.parse.quote(host)}&protocol={protocol}"
    try:
        data = get(url)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"{host} {protocol}: {exc}") from exc

    config = data.decode("utf-8", "ignore").strip()
    if not config.startswith("client") or "remote " not in config:
        raise RuntimeError(f"{host} {protocol}: invalid OpenVPN config")
    if not re.search(rf"(?m)^\s*remote\s+{re.escape(host)}\s+{PROTOCOLS[protocol][1]}\b", config, re.I):
        raise RuntimeError(f"{host} {protocol}: unexpected remote endpoint")
    return config


def build():
    page = get(PAGE).decode("utf-8", "ignore")
    password = parse_password(page)
    updated_at = parse_updated_at(page)
    servers = parse_servers(page)

    for server in servers:
        configs = {}
        for key, (transport, port) in PROTOCOLS.items():
            print(f"Fetching {server['id']} {transport} {port}...")
            configs[key] = fetch_config(server["host"], key)
        server["configs"] = {
            key: {"type": PROTOCOLS[key][0], "port": PROTOCOLS[key][1], "config": config}
            for key, config in configs.items()
        }

    if len(servers) < 5 or not valid_password(password):
        raise RuntimeError("Refusing to publish incomplete VPNBook catalog")

    catalog = {
        "source": "VPNBook",
        "username": USER,
        "password": password,
        "updatedAt": updated_at,
        "protocols": list(PROTOCOLS),
        "servers": servers,
    }
    new_data = json.dumps(catalog, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists() and OUT.read_text(encoding="utf-8") == new_data:
        print("Catalog unchanged")
        return

    OUT.write_text(new_data, encoding="utf-8")
    print(f"Catalog updated: {len(servers)} servers")


if __name__ == "__main__":
    try:
        build()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
