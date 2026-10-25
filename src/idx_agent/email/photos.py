"""Bounded photo references from the feed; never download a URL or trust its text."""

import html
import ipaddress
import json
import re
from urllib.parse import unquote, urlsplit

from idx_agent.db.listings import _candidate_keys, _where
from idx_agent.domain.models import PropertySearchFilters
from idx_agent.email.bodies import check_content
from idx_agent.safety.approval import ApprovalRefused
from idx_agent.safety.columns import check_column


def safe_photo_url(value):
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return None
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        if (
            url.scheme != "https"
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.port not in {None, 443}
            or "." not in host
            or not re.fullmatch(r"[A-Za-z0-9.-]+", host)
            or any(
                not part or part.startswith("-") or part.endswith("-")
                for part in host.split(".")
            )
            or host.lower().endswith((".local", ".localhost", ".internal"))
            or not re.fullmatch(r"/[A-Za-z0-9_./~%+-]+", url.path)
            or not re.fullmatch(r"/[A-Za-z0-9_./~+-]+", unquote(url.path))
            or any(part in {".", ".."} for part in unquote(url.path).split("/"))
        ):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        # The feed's image filenames contain long numeric identifiers. Those are
        # image resources, not phone fields. Validate the rest of the URL with the
        # ordinary content guard; separated phone shapes and contact words remain
        # refused. This exception applies only to validated Photo lines.
        scanned_path = re.sub(r"[0-9]{10,}", "[image-id]", unquote(url.path))
        check_content("Photo", url._replace(path=scanned_path).geturl())
    except (ValueError, ApprovalRefused):
        return None
    return value


def photo_urls(raw):
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    if not isinstance(values, list):
        return []
    return list(
        dict.fromkeys(url for item in values[:100] if (url := safe_photo_url(item)))
    )[:3]


def fetch_photos(keys, conn):
    keys = _candidate_keys(keys)
    if len(keys) > 10:
        raise ValueError("at most ten photo sets")
    key, photos, modified = (
        check_column("rets_property", name)
        for name in ("L_ListingID", "L_Photos", "ModificationTimestamp")
    )
    where, params = _where(PropertySearchFilters())
    marks = ", ".join(["%s"] * len(keys))
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT {key}, {photos} FROM rets_property WHERE {where} "
            f"AND {key} IN ({marks}) ORDER BY {key}, {modified} DESC LIMIT %s",
            (*params, *(str(k) for k in keys), 50),
        )
        rows = cursor.fetchall()
    if len(rows) > 50:
        raise ValueError("photo row cap exceeded")
    found = {}
    for row in rows:
        number = int(row[key])
        if number not in keys:
            raise ValueError("unexpected photo key")
        found.setdefault(number, photo_urls(row[photos]))
    return found


def render_html(body):
    """HTML mirrors approved plain text; only approved Photo lines become images."""
    lines = []
    for line in body.splitlines():
        match = re.fullmatch(r"Photo ([1-3]): (https://\S+)", line)
        url = safe_photo_url(match[2]) if match else None
        if url:
            escaped = html.escape(url, quote=True)
            lines.append(
                f'<p>Photo {match[1]}<br><a href="{escaped}">'
                f'<img src="{escaped}" alt="Listing photo {match[1]}" '
                'width="480"></a></p>'
            )
        else:
            lines.append(html.escape(line) + "<br>")
    return "<!doctype html><html><body>" + "\n".join(lines) + "</body></html>"
