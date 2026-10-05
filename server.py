"""
GumroadDNA: a VibeDNA MCP server
Complete headless Gumroad control via the Gumroad API v2 (no browser). 44 tools:
- Products: create + upload (multipart-S3) + cover/thumbnail + publish + archive + download
- Sales: list individual sales, view, refund (full/partial), resend receipt, mark shipped
- Customers: list + view subscribers/members
- Licenses: verify / enable / disable / decrement uses
- Discounts: list / create / delete offer codes
- Custom fields, webhooks (resource subscriptions), account
- Plus VibeDNA extras: niche/market research, buyer -> Resend sync, unlisted-asset scan
"""

import os
import base64
import hashlib
import mimetypes
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("gumroad-dna")

BASE_URL = "https://api.gumroad.com/v2"

# This copy's version. Bump it when packaging; check_for_update compares it against
# what the site currently publishes, so an installed copy can tell it is behind.
VERSION = "2.2.0"
PRODUCT_SLUG = "gumroad"


@mcp.tool()
def check_for_update() -> str:
    """Is this copy behind the published version?

    Your copy is a folder on your machine, so it stays exactly as it was the day you
    installed it while fixes keep shipping. This asks what is published now and tells
    you whether to update, and how. It sends nothing about you: just a version number
    comes back."""
    try:
        r = requests.get("https://vibedna.ai/api/mcp/latest",
                         params={"slug": PRODUCT_SLUG}, timeout=15)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        return f"could not reach the update check ({type(e).__name__}). Your copy still works; try later."

    latest = str(d.get("version") or "")
    if not latest:
        return "the update service did not report a version. Nothing to do."

    def parts(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except Exception:
            return (0,)

    if parts(latest) <= parts(VERSION):
        return f"up to date (you have {VERSION}, published is {latest})."

    return "\n".join([
        f"UPDATE AVAILABLE: you have {VERSION}, published is {latest}.",
        "",
        "To update, from the same email you got it with:",
        f"  1. Download: https://vibedna.ai/api/download?slug={PRODUCT_SLUG}&license=<your key>",
        "     (your key is in your purchase email, and in your library at vibedna.ai/library)",
        "  2. Unzip over your current folder, keeping your own files:",
        "     your .env with your store token stays as it is.",
        "  3. Restart your AI so it loads the new tools.",
        "",
        "Nothing of yours is stored in this folder: your products, sales and customers",
        "live in your store account. An update replaces code only.",
    ])

UPGRADE_MSG = ""


def _is_paid() -> bool:
    # GumroadDNA went fully free 2026-07-10: every tool unlocked, no license key.
    return True


def _token() -> str:
    t = os.getenv("GUMROAD_ACCESS_TOKEN", "").strip()
    if not t:
        raise ValueError("GUMROAD_ACCESS_TOKEN not set.")
    return t


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}"}


def _get(endpoint: str, params: dict | None = None) -> dict:
    r = requests.get(f"{BASE_URL}{endpoint}", headers=_headers(), params=params or {}, timeout=20)
    r.raise_for_status()
    return r.json()


def _post(endpoint: str, data: dict) -> dict:
    r = requests.post(f"{BASE_URL}{endpoint}", headers=_headers(), data=data, timeout=20)
    r.raise_for_status()
    return r.json()


def _put(endpoint: str, data: dict | None = None) -> dict:
    r = requests.put(f"{BASE_URL}{endpoint}", headers=_headers(), data=data or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def _delete(endpoint: str) -> None:
    requests.delete(f"{BASE_URL}{endpoint}", headers=_headers(), timeout=30)


def _post_json(endpoint: str, body: dict) -> dict:
    r = requests.post(f"{BASE_URL}{endpoint}", headers={**_headers(), "Content-Type": "application/json"},
                      json=body, timeout=180)
    r.raise_for_status()
    return r.json()


def _direct_upload_image(path: str) -> str:
    """ActiveStorage direct upload (images/video ONLY) -> returns signed_blob_id. For covers/thumbnails."""
    data = open(path, "rb").read()
    md5 = base64.b64encode(hashlib.md5(data).digest()).decode()
    ctype = mimetypes.guess_type(path)[0] or "image/png"
    resp = _post("/direct_uploads", {"blob[filename]": os.path.basename(path), "blob[byte_size]": len(data),
                                     "blob[checksum]": md5, "blob[content_type]": ctype})
    du = resp.get("direct_upload") or {}
    put = requests.put(du.get("url"), data=data, headers=du.get("headers") or {}, timeout=300)
    put.raise_for_status()
    return resp.get("signed_id")


def _upload_product_file(path: str, content_type: str = "application/zip") -> str:
    """Multipart-S3 upload for product files (any size/type) -> returns file_url for the create/update files array."""
    data = open(path, "rb").read()
    sz = len(data)
    presign = _post("/files/presign", {"filename": os.path.basename(path), "file_size": sz,
                                       "content_type": content_type})
    uid, key, file_url = presign["upload_id"], presign["key"], presign["file_url"]
    parts = presign.get("parts") or []
    n = len(parts)
    psize = -(-sz // n)  # ceil
    done = []
    try:
        for pinfo in sorted(parts, key=lambda p: int(p["part_number"])):
            pn = int(pinfo["part_number"])
            chunk = data[(pn - 1) * psize: pn * psize]
            pr = requests.put(pinfo["presigned_url"], data=chunk, timeout=900)
            pr.raise_for_status()
            done.append({"part_number": pn, "etag": (pr.headers.get("ETag") or "").strip('"')})
    except requests.HTTPError:
        _post("/files/abort", {"upload_id": uid, "key": key})
        raise
    comp = _post_json("/files/complete", {"upload_id": uid, "key": key, "parts": done})
    return comp.get("file_url") or file_url


def _set_only_cover(pid: str, image_path: str) -> None:
    """Remove existing covers, then upload image as the sole (main) cover."""
    prod = _get(f"/products/{pid}").get("product", {}) or {}
    for c in prod.get("covers", []):
        _delete(f"/products/{pid}/covers/{c.get('id')}")
    signed = _direct_upload_image(image_path)
    _post(f"/products/{pid}/covers", {"signed_blob_id": signed})


def _add_cover(pid: str, image_path: str) -> None:
    """Append a gallery/preview cover image (does NOT remove existing)."""
    signed = _direct_upload_image(image_path)
    _post(f"/products/{pid}/covers", {"signed_blob_id": signed})


def _set_thumbnail(pid: str, image_path: str) -> None:
    """Set the small grid thumbnail image."""
    signed = _direct_upload_image(image_path)
    _post(f"/products/{pid}/thumbnail", {"signed_blob_id": signed})


def _square_image(src_path: str, size: int = 600) -> str:
    """Best-effort: pad src into a size x size square JPEG (full art, nothing cropped) for a clean
    grid thumbnail. Returns a new .sq.jpg path, or the original path if Pillow isn't installed."""
    try:
        from PIL import Image
    except Exception:
        return src_path
    try:
        im = Image.open(src_path).convert("RGB")
        w, h = im.size
        corners = [im.getpixel((1, 1)), im.getpixel((w - 2, 1)),
                   im.getpixel((1, h - 2)), im.getpixel((w - 2, h - 2))]
        bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
        im.thumbnail((size, size), Image.LANCZOS)
        canvas = Image.new("RGB", (size, size), bg)
        canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
        out = src_path + ".sq.jpg"
        canvas.save(out, "JPEG", quality=92)
        return out
    except Exception:
        return src_path


def _sniff_ext(b: bytes) -> str:
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "img"


# ── Free tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def get_revenue_snapshot(period: str = "month") -> str:
    """[FREE] Total sales and revenue for today, last 7 days, or last 30 days. period: today | week | month"""
    try:
        data = _get("/sales")
    except ValueError as e:
        return str(e)
    sales = data.get("sales", [])

    now = datetime.now(timezone.utc)
    if period == "today":
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "Today"
    elif period == "week":
        cutoff = now - timedelta(days=7)
        label = "Last 7 days"
    else:
        cutoff = now - timedelta(days=30)
        label = "Last 30 days"

    filtered = []
    for s in sales:
        try:
            created = datetime.fromisoformat(s.get("created_at", "").replace("Z", "+00:00"))
        except Exception:
            continue
        if created >= cutoff:
            filtered.append(s)

    total_revenue = sum(s.get("price", 0) for s in filtered) / 100
    net = sum(s.get("price", 0) for s in filtered if not s.get("refunded", False)) / 100
    refunded = sum(1 for s in filtered if s.get("refunded", False))

    return "\n".join([
        f"Revenue Snapshot - {label}",
        f"  Total sales:    {len(filtered)}",
        f"  Gross revenue:  ${total_revenue:.2f}",
        f"  Refunds:        {refunded}",
        f"  Net revenue:    ${net:.2f}",
    ])


@mcp.tool()
def list_products() -> str:
    """[FREE] All Gumroad products with price, sales count, and published status."""
    try:
        data = _get("/products")
    except ValueError as e:
        return str(e)
    products = data.get("products", [])
    if not products:
        return "No products found."

    lines = [f"Products ({len(products)} total)\n"]
    for p in products:
        price_cents = p.get("price", 0)
        price = f"${price_cents / 100:.2f}" if price_cents else "FREE"
        status = "Published" if p.get("published", False) else "Unlisted"
        lines.append(
            f"  [{status}] {p.get('name', 'Unnamed')}\n"
            f"    ID:     {p.get('id', '')}\n"
            f"    Price:  {price}\n"
            f"    Sales:  {p.get('sales_count', 0)}\n"
            f"    URL:    {p.get('short_url', '')}\n"
        )
    return "\n".join(lines)


@mcp.tool()
def scan_gumroad_niche(keyword: str, max_results: int = 20) -> str:
    """[FREE] Research a Gumroad niche - market size, price distribution, adjacent-demand tags, and top
    sellers by rating count. Reads the public Gumroad discover page (no auth, works for any keyword,
    not just your own products)."""
    import html as _html
    import json as _json
    from urllib.parse import quote

    url = f"https://gumroad.com/discover?query={quote(keyword)}"
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=20,
        )
    except requests.RequestException as e:
        return f"Error reaching Gumroad discover: {e}"
    if r.status_code != 200:
        return f"Gumroad discover returned {r.status_code}. Try again shortly."

    # The discover page embeds an HTML-escaped `search_results` JSON blob. Balance-brace extract it.
    un = _html.unescape(r.text)
    i = un.find('"search_results":')
    if i < 0:
        return f"No search data found for '{keyword}' (Gumroad may have changed the discover page)."
    j = un.find("{", i)
    depth, k = 0, j
    while k < len(un):
        if un[k] == "{":
            depth += 1
        elif un[k] == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    try:
        sr = _json.loads(un[j:k + 1])
    except _json.JSONDecodeError as e:
        return f"Could not parse Gumroad discover data: {e}"

    products = sr.get("products", [])
    if not products:
        return f"No Gumroad products found for '{keyword}'."

    prices = [p["price_cents"] / 100 for p in products if p.get("price_cents") is not None]
    paid = [x for x in prices if x > 0]
    total = sr.get("total")
    tags = sr.get("tags_data", [])[:8]
    ftypes = sr.get("filetypes_data", [])[:6]

    lines = [
        f"Gumroad Niche Scan: '{keyword}'",
        f"  Market size:   {total:,} products" if isinstance(total, int) else f"  Market size:   {total}",
        f"  Sampled:       {len(products)} listings on page 1",
    ]
    if paid:
        avg = sum(paid) / len(paid)
        lines.append(f"  Paid price:    ${min(paid):.0f} - ${max(paid):.0f}  (avg ${avg:.0f})")
    free_n = sum(1 for x in prices if x == 0)
    if free_n:
        lines.append(f"  Free listings: {free_n}/{len(prices)} (lead magnets - funnel to paid)")

    if tags:
        lines.append("")
        lines.append("  Adjacent demand (tag · products):")
        for t in tags:
            lines.append(f"    {t.get('key')} · {t.get('doc_count'):,}")

    if ftypes:
        lines.append("")
        lines.append("  Formats that sell: " + ", ".join(f"{f.get('key')}({f.get('doc_count')})" for f in ftypes))

    top = sorted(products, key=lambda p: p.get("ratings", {}).get("count", 0), reverse=True)[:max_results][:10]
    lines.append("")
    lines.append("  Top sellers (by rating count = sales proxy):")
    for p in top:
        rc = p.get("ratings", {}).get("count", 0)
        avg_r = p.get("ratings", {}).get("average", 0)
        price = p.get("price_cents", 0) / 100
        lines.append(f"    - {p.get('name', 'Unknown')[:60]} - ${price:.0f} · {rc} ratings ({avg_r}★)")
        if p.get("url"):
            lines.append(f"      {p['url'].split('?')[0]}")
    return "\n".join(lines)


# ── Paid tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def update_product(product_id: str, name: str = "", description: str = "", price: float = 0, published: bool = None) -> str:
    """[FREE] Edit a Gumroad product. Pass product_id and any fields to change."""
    if not _is_paid():
        return UPGRADE_MSG
    payload = {}
    if name:
        payload["name"] = name
    if description:
        payload["description"] = description
    if price:
        payload["price"] = str(int(price * 100))
    if published is not None:
        payload["published"] = "true" if published else "false"
    if not payload:
        return "Nothing to update - provide at least one of: name, description, price, published."
    try:
        result = _put(f"/products/{product_id}", payload)
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    p = result.get("product", {})
    return (
        f"Product updated.\n"
        f"  Name:      {p.get('name')}\n"
        f"  Price:     ${p.get('price', 0) / 100:.2f}\n"
        f"  Published: {p.get('published')}\n"
        f"  URL:       {p.get('short_url')}"
    )


@mcp.tool()
def launch_product(name: str, price: float = 0, description: str = "", published: bool = False) -> str:
    """[FREE] Create a new Gumroad product listing."""
    if not _is_paid():
        return UPGRADE_MSG
    payload = {"name": name, "price": str(int(price * 100))}
    if description:
        payload["description"] = description
    if published:
        payload["published"] = "true"
    try:
        result = _post("/products", payload)
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    p = result.get("product") or result
    pid = p.get("id") or p.get("permalink") or p.get("custom_permalink")
    return (
        f"Product created!\n"
        f"  Name:      {p.get('name')}\n"
        f"  ID:        {pid}\n"
        f"  Price:     ${p.get('price', 0) / 100:.2f}\n"
        f"  Published: {p.get('published', False)}\n"
        f"  Edit URL:  https://app.gumroad.com/products/{pid}/edit\n"
        f"  Short URL: {p.get('short_url')}\n"
        f"  Raw keys:  {list(result.keys())}"
    )


@mcp.tool()
def scan_unlisted_assets(projects: list) -> str:
    """[FREE] Cross-reference project names against Gumroad listings - find monetization gaps."""
    if not _is_paid():
        return UPGRADE_MSG
    try:
        data = _get("/products")
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    listed = {p.get("name", "").lower() for p in data.get("products", [])}
    gaps = [p for p in projects if p.lower() not in listed]
    if not gaps:
        return "All provided projects have matching Gumroad listings."
    lines = [f"Unlisted assets ({len(gaps)} gaps):", ""]
    lines += [f"  - {g}" for g in gaps]
    lines.append("\nRun launch_product for each to create listings.")
    return "\n".join(lines)


@mcp.tool()
def sync_buyers_to_resend(product_id: str = "") -> str:
    """[FREE] Pull buyer emails from Gumroad sales, formatted for Resend audience import."""
    if not _is_paid():
        return UPGRADE_MSG
    params = {"product_id": product_id} if product_id else {}
    try:
        data = _get("/sales", params)
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    sales = data.get("sales", [])
    seen, contacts = set(), []
    for s in sales:
        email = s.get("email", "").strip().lower()
        if email and email not in seen:
            seen.add(email)
            contacts.append({
                "email": email,
                "first_name": (s.get("full_name", "") or "").split()[0],
                "product": s.get("product_name", ""),
            })
    if not contacts:
        return "No buyer emails found."
    lines = [f"Buyer Export - {len(contacts)} unique emails\n", "email | first_name | product\n"]
    lines += [f"  {c['email']} | {c['first_name']} | {c['product']}" for c in contacts]
    lines.append("\nTip: Pass to resend-mcp add_contact with your audience_id to import.")
    return "\n".join(lines)



@mcp.tool()
def get_stock_status() -> str:
    """[FREE] Stock status for every product - sales_count, max_purchase_count, remaining. 'inf' = unlimited."""
    try:
        data = _get("/products")
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    products = data.get("products", [])
    if not products:
        return "No products found."
    rows = [f"{'Product':<58} {'Sold':>5} {'Limit':>6} {'Left':>5}", "-" * 80]
    for p in products:
        name = (p.get("name") or "Unknown")[:56]
        sold = p.get("sales_count", 0) or 0
        cap = p.get("max_purchase_count")
        if cap is None:
            limit, left = "inf", "inf"
        else:
            limit = str(cap)
            left = str(max(cap - sold, 0))
        rows.append(f"{name:<58} {sold:>5} {limit:>6} {left:>5}")
    return "\n".join(rows)


@mcp.tool()
def update_stock(product_id: str, max_purchase_count: int) -> str:
    """[FREE] Set max_purchase_count (scarcity limit) on a product. Use 0 to remove the limit."""
    if max_purchase_count < 0:
        return "Error: max_purchase_count must be >= 0 (use 0 to remove limit)."
    payload = {"max_purchase_count": str(max_purchase_count) if max_purchase_count > 0 else ""}
    try:
        result = _put(f"/products/{product_id}", payload)
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    p = result.get("product", {})
    sold = p.get("sales_count", 0) or 0
    cap = p.get("max_purchase_count")
    limit = "unlimited" if cap is None else str(cap)
    left = "inf" if cap is None else str(max(cap - sold, 0))
    return (
        f"Stock updated.\n"
        f"  Product: {p.get('name')}\n"
        f"  Sold:    {sold}\n"
        f"  Limit:   {limit}\n"
        f"  Left:    {left}"
    )


@mcp.tool()
def bump_stock(buffer: int = 5, dry_run: bool = False) -> str:
    """[FREE] Keep N copies "left" on every limited product. Sets max_purchase_count = sales_count + buffer.
    Skips products with no existing limit (unlimited products). buffer: how many copies always visible. dry_run: preview without writing."""
    if buffer < 1:
        return "Error: buffer must be >= 1."
    try:
        data = _get("/products")
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    products = data.get("products", [])
    actions, skipped = [], []
    for p in products:
        name = p.get("name", "Unknown")
        cap = p.get("max_purchase_count")
        sold = p.get("sales_count", 0) or 0
        if cap is None:
            skipped.append(f"  - {name[:56]} (unlimited)")
            continue
        target = sold + buffer
        if target == cap:
            actions.append(f"  = {name[:56]}: already at {cap} (sold {sold}, left {cap - sold})")
            continue
        if dry_run:
            actions.append(f"  ~ {name[:56]}: {cap} -> {target} (sold {sold})")
            continue
        try:
            _put(f"/products/{p['id']}", {"max_purchase_count": str(target)})
            actions.append(f"  + {name[:56]}: {cap} -> {target} (sold {sold}, now {buffer} left)")
        except (ValueError, requests.HTTPError) as e:
            actions.append(f"  ! {name[:56]}: FAILED - {e}")
    header = f"Stock bump (buffer={buffer}, dry_run={dry_run})"
    return "\n".join([header, "-" * len(header), *actions, "", "Skipped (unlimited):", *skipped])


@mcp.tool()
def vibedna_info() -> dict:
    """Product info - VibeDNA build, version, license, support."""
    return {
        "product": "gumroad-dna",
        "display_name": "GumroadDNA",
        "vendor": "VibeDNA",
        "version": VERSION,
        "tools": 44,
        "site": "https://vibedna.ai/store",
        "license": "MIT",
        "support": "admin@vibedna.ai",
        "source": "https://github.com/marstudio360/gumroad-dna-mcp",
        "series": "DNA Series",
    }


@mcp.tool()
def create_product(name: str, price: float, description: str = "", file_path: str = "",
                   cover_path: str = "", tags: list = None, publish: bool = False,
                   thumbnail_path: str = "") -> str:
    """[FREE] Create a Gumroad product END-TO-END via the API (no browser). Uploads the product
    file (any size, multipart-S3), sets the cover image, ALSO sets the square grid thumbnail
    (so the product never shows imageless in the grid/library), writes the description, and
    optionally publishes. file_path = the product zip/download; cover_path = the cover image
    (JPEG/PNG); thumbnail_path = optional dedicated square thumbnail (defaults to the cover).
    Use whenever the user wants to launch/upload a new Gumroad product."""
    if not _is_paid():
        return UPGRADE_MSG
    try:
        cents = int(round(price * 100))
        if file_path:
            file_url = _upload_product_file(file_path)
            body = {"name": name, "native_type": "digital", "price": cents,
                    "price_currency_type": "usd", "description": description,
                    "files": [{"id": "1", "url": file_url,
                               "display_name": os.path.splitext(os.path.basename(file_path))[0]}]}
            if tags:
                body["tags"] = tags
            result = _post_json("/products", body)
        else:
            payload = {"name": name, "native_type": "digital", "price": str(cents),
                       "description": description}
            result = _post("/products", payload)
        p = result.get("product") or result
        pid = p.get("id")
        extra = ""
        if cover_path and pid:
            _set_only_cover(pid, cover_path)
            extra += " + cover"
        # ALWAYS set a grid thumbnail when we have any image, else the product shows imageless
        # in the grid/library (Gumroad covers and thumbnails are separate slots). 2026-07-18.
        thumb_src = thumbnail_path or cover_path
        if thumb_src and pid:
            try:
                _set_thumbnail(pid, _square_image(thumb_src))
                extra += " + thumbnail"
            except (ValueError, requests.HTTPError):
                pass
        if publish and pid:
            _put(f"/products/{pid}/enable")
            extra += " + PUBLISHED"
        return (f"Product created{extra}.\n"
                f"  Name:  {p.get('name')}\n"
                f"  ID:    {pid}\n"
                f"  Price: ${price:.2f}\n"
                f"  File:  {'yes' if file_path else 'none'}\n"
                f"  URL:   {p.get('short_url')}\n"
                f"  Published: {publish}")
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def set_product_cover(product_id: str, image_path: str) -> str:
    """[FREE] Replace a product's cover image (removes existing covers, uploads image_path as the
    sole/main cover). image_path must be JPEG/PNG/GIF."""
    if not _is_paid():
        return UPGRADE_MSG
    try:
        _set_only_cover(product_id, image_path)
        return f"Cover set for {product_id} from {os.path.basename(image_path)}."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def add_product_file(product_id: str, file_path: str, content_type: str = "application/zip") -> str:
    """[FREE] Upload a file (multipart-S3) and attach it to an existing product's downloads."""
    if not _is_paid():
        return UPGRADE_MSG
    try:
        file_url = _upload_product_file(file_path, content_type)
        name = os.path.splitext(os.path.basename(file_path))[0]
        _put(f"/products/{product_id}",
             {"files": [{"id": "1", "url": file_url, "display_name": name}]})
        return f"Attached {os.path.basename(file_path)} to {product_id}."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def archive_product(product_id: str) -> str:
    """[FREE] Unpublish/archive a product (PUT /products/{id}/disable). Reversible via publish_product."""
    if not _is_paid():
        return UPGRADE_MSG
    try:
        _put(f"/products/{product_id}/disable")
        return f"Archived (unpublished) {product_id}."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def publish_product(product_id: str) -> str:
    """[FREE] Publish a product live (PUT /products/{id}/enable)."""
    if not _is_paid():
        return UPGRADE_MSG
    try:
        _put(f"/products/{product_id}/enable")
        return f"Published {product_id} - now live and buyable."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def download_product_files(product_id: str, out_dir: str) -> str:
    """[FREE] Download a product's own files (seller) to out_dir using the API's signed file URLs."""
    if not _is_paid():
        return UPGRADE_MSG
    try:
        prod = _get(f"/products/{product_id}").get("product", {}) or {}
        files = prod.get("files", [])
        if not files:
            return "No files on this product."
        os.makedirs(out_dir, exist_ok=True)
        saved = []
        for f in files:
            fn = f"{f.get('name')}.{f.get('filetype')}" if f.get("filetype") else f.get("name")
            dest = os.path.join(out_dir, fn)
            r = requests.get(f["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=300)
            r.raise_for_status()
            open(dest, "wb").write(r.content)
            saved.append(f"{fn} ({len(r.content)//1024//1024} MB)")
        return f"Downloaded {len(saved)} file(s) to {out_dir}:\n  " + "\n  ".join(saved)
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def add_product_image(product_id: str, image_path: str, as_thumbnail: bool = False) -> str:
    """[FREE] Add an image to a product. as_thumbnail=True sets the small grid thumbnail;
    otherwise APPENDS a gallery/preview cover image (keeps existing ones). JPEG/PNG/GIF only."""
    if not _is_paid():
        return UPGRADE_MSG
    try:
        if as_thumbnail:
            _set_thumbnail(product_id, image_path)
            return f"Thumbnail set for {product_id} from {os.path.basename(image_path)}."
        _add_cover(product_id, image_path)
        return f"Gallery image added to {product_id} from {os.path.basename(image_path)}."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def list_product_images(product_id: str) -> str:
    """[FREE] List a product's images - gallery covers (id, MAIN flag, url) + thumbnail url."""
    try:
        pr = _get(f"/products/{product_id}").get("product", {}) or {}
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    covers = pr.get("covers", [])
    main = pr.get("main_cover_id")
    lines = [f"Images - {pr.get('name', '?')}",
             f"  thumbnail: {pr.get('thumbnail_url') or '(none)'}",
             f"  gallery covers ({len(covers)}):"]
    for c in covers:
        flag = " [MAIN]" if c.get("id") == main else ""
        lines.append(f"    - {c.get('id')}{flag}  {c.get('url', '')}")
    return "\n".join(lines)


@mcp.tool()
def remove_product_image(product_id: str, cover_id: str) -> str:
    """[FREE] Remove a gallery/cover image by cover_id (get IDs from list_product_images)."""
    if not _is_paid():
        return UPGRADE_MSG
    try:
        _delete(f"/products/{product_id}/covers/{cover_id}")
        return f"Removed cover {cover_id} from {product_id}."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def reorder_product_images(product_id: str, cover_ids: list) -> str:
    """[FREE] Reorder gallery images by passing cover_ids in the desired order - the FIRST becomes
    the main cover shown on the storefront."""
    if not _is_paid():
        return UPGRADE_MSG
    try:
        _put(f"/products/{product_id}", {"cover_ids[]": cover_ids})
        return f"Reordered {len(cover_ids)} covers (first = main) on {product_id}."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def download_product_images(product_id: str, out_dir: str) -> str:
    """[FREE] Download a product's marketing images (all gallery covers + thumbnail) to out_dir."""
    try:
        pr = _get(f"/products/{product_id}").get("product", {}) or {}
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    targets = []
    for i, c in enumerate(pr.get("covers", []), 1):
        u = c.get("original_url") or c.get("url")
        if u:
            targets.append((f"cover_{i}", u))
    if pr.get("thumbnail_url"):
        targets.append(("thumbnail", pr["thumbnail_url"]))
    if not targets:
        return "No images on this product."
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for label, u in targets:
        try:
            r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
            r.raise_for_status()
            dest = os.path.join(out_dir, f"{label}.{_sniff_ext(r.content)}")
            open(dest, "wb").write(r.content)
            saved.append(f"{os.path.basename(dest)} ({len(r.content)//1024} KB)")
        except requests.HTTPError:
            continue
    return f"Downloaded {len(saved)} image(s) to {out_dir}:\n  " + "\n  ".join(saved)


# ── Customers · Sales · Licenses · Discounts · Webhooks (full Gumroad API v2) ────
import json as _json


def _del(endpoint: str) -> dict:
    """DELETE that returns the JSON body (Gumroad returns {success: true})."""
    r = requests.delete(f"{BASE_URL}{endpoint}", headers=_headers(), timeout=30)
    try:
        return r.json()
    except Exception:
        return {"success": r.ok}


# ---- Sales ----
@mcp.tool()
def list_sales(after: str = "", before: str = "", product_id: str = "", email: str = "", page_key: str = "") -> str:
    """[FREE] List individual sales (not just the total). Filter by date (after/before as YYYY-MM-DD),
    product_id, or buyer email. Paginate with page_key from the previous response. This is the real
    per-sale ledger: who bought what, when, for how much."""
    params = {k: v for k, v in {"after": after, "before": before, "product_id": product_id, "email": email, "page_key": page_key}.items() if v}
    try:
        data = _get("/sales", params)
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    sales = data.get("sales", [])
    lines = [f"Sales: {len(sales)} on this page" + (f" · next page_key: {data['next_page_key']}" if data.get("next_page_key") else "")]
    for s in sales[:50]:
        lines.append(f"  {s.get('created_at','?')[:10]} · {s.get('email','?')} · {s.get('product_name','?')[:36]} · ${(s.get('price',0))/100:.2f} · id={s.get('id')}")
    return "\n".join(lines) if sales else "No sales for those filters."


@mcp.tool()
def get_sale(sale_id: str) -> str:
    """[FREE] Full detail of one sale by id: buyer, product, price, variants, custom fields, refund/dispute state."""
    try:
        return _json.dumps(_get(f"/sales/{sale_id}").get("sale", {}), indent=2, default=str)
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def refund_sale(sale_id: str, amount_cents: int = 0) -> str:
    """[FREE] Refund a sale. Leave amount_cents=0 for a FULL refund, or pass cents for a partial refund."""
    body = {"amount_cents": str(amount_cents)} if amount_cents > 0 else {}
    try:
        r = _put(f"/sales/{sale_id}/refund", body)
        s = r.get("sale", {})
        return f"Refunded sale {sale_id}. refunded={s.get('refunded')} partially_refunded={s.get('partially_refunded')}"
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def resend_receipt(sale_id: str) -> str:
    """[FREE] Re-send the purchase receipt email to the buyer of a sale."""
    try:
        _post(f"/sales/{sale_id}/resend_receipt", {})
        return f"Receipt re-sent for sale {sale_id}."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def mark_as_shipped(sale_id: str, tracking_url: str = "") -> str:
    """[FREE] Mark a physical-good sale as shipped, optionally with a tracking URL."""
    body = {"tracking_url": tracking_url} if tracking_url else {}
    try:
        _put(f"/sales/{sale_id}/mark_as_shipped", body)
        return f"Sale {sale_id} marked as shipped." + (f" Tracking: {tracking_url}" if tracking_url else "")
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


# ---- Subscribers / customers ----
@mcp.tool()
def list_subscribers(product_id: str, email: str = "") -> str:
    """[FREE] List subscribers (recurring customers / members) for a product. Optionally filter by email.
    Shows status, current period, and cancellation state for each."""
    params = {"email": email} if email else {}
    try:
        subs = _get(f"/products/{product_id}/subscribers", params).get("subscribers", [])
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    if not subs:
        return "No subscribers found."
    lines = [f"Subscribers: {len(subs)}"]
    for s in subs[:60]:
        lines.append(f"  {s.get('user_email','?')} · status={s.get('status','?')} · since {str(s.get('created_at',''))[:10]} · id={s.get('id')}")
    return "\n".join(lines)


@mcp.tool()
def get_subscriber(subscriber_id: str) -> str:
    """[FREE] Full detail of one subscriber: email, status, billing period, charges, cancellation."""
    try:
        return _json.dumps(_get(f"/subscribers/{subscriber_id}").get("subscriber", {}), indent=2, default=str)
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


# ---- Licenses ----
@mcp.tool()
def verify_license(product_id: str, license_key: str, increment_uses: bool = False) -> str:
    """[FREE] Verify a license key for a product. Returns whether it's valid + the purchase behind it.
    Set increment_uses=True to count this as a use (for seat/activation limits)."""
    body = {"product_id": product_id, "license_key": license_key, "increment_uses_count": "true" if increment_uses else "false"}
    try:
        r = _post("/licenses/verify", body)
        p = r.get("purchase", {})
        return f"VALID. uses={r.get('uses')} · buyer={p.get('email','?')} · refunded={p.get('refunded')} · disputed={p.get('disputed')} · subscription_cancelled={p.get('subscription_cancelled_at') is not None}"
    except requests.HTTPError as e:
        return f"INVALID or error: {e}"
    except ValueError as e:
        return f"Error: {e}"


@mcp.tool()
def enable_license(product_id: str, license_key: str) -> str:
    """[FREE] Enable (re-activate) a license key."""
    try:
        _put("/licenses/enable", {"product_id": product_id, "license_key": license_key})
        return f"License enabled."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def disable_license(product_id: str, license_key: str) -> str:
    """[FREE] Disable a license key (revoke access, e.g. on refund/abuse)."""
    try:
        _put("/licenses/disable", {"product_id": product_id, "license_key": license_key})
        return f"License disabled."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def decrement_license_uses(product_id: str, license_key: str) -> str:
    """[FREE] Decrement a license's use count by one (e.g. free up a seat)."""
    try:
        r = _put("/licenses/decrement_uses_count", {"product_id": product_id, "license_key": license_key})
        return f"Decremented. uses now = {r.get('uses')}"
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


# ---- Offer codes / discounts ----
@mcp.tool()
def list_offer_codes(product_id: str) -> str:
    """[FREE] List discount / offer codes for a product."""
    try:
        codes = _get(f"/products/{product_id}/offer_codes").get("offer_codes", [])
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    if not codes:
        return "No offer codes."
    lines = ["Offer codes:"]
    for c in codes:
        off = f"{c.get('amount_off')}%" if c.get('amount_percentage') is not None or c.get('offer_type') == 'percent' else f"${(c.get('amount_off') or 0)/100:.2f}"
        lines.append(f"  {c.get('name')} · {off} off · used {c.get('times_used','?')}/{c.get('max_purchase_count') or '∞'} · id={c.get('id')}")
    return "\n".join(lines)


@mcp.tool()
def create_offer_code(product_id: str, code: str, amount_off: int, percent: bool = True, max_uses: int = 0) -> str:
    """[FREE] Create a discount code. amount_off = the number (percent if percent=True, else cents).
    max_uses=0 means unlimited. e.g. create_offer_code(pid, 'LAUNCH20', 20, percent=True)."""
    body = {"name": code, "amount_off": str(amount_off), "offer_type": "percent" if percent else "cents"}
    if max_uses > 0:
        body["max_purchase_count"] = str(max_uses)
    try:
        r = _post(f"/products/{product_id}/offer_codes", body)
        return f"Created code '{code}' ({amount_off}{'%' if percent else ' cents'} off). id={r.get('offer_code',{}).get('id')}"
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def delete_offer_code(product_id: str, offer_code_id: str) -> str:
    """[FREE] Delete a discount code by its id."""
    try:
        ok = _del(f"/products/{product_id}/offer_codes/{offer_code_id}").get("success")
        return "Deleted." if ok else "Delete may have failed."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


# ---- Custom fields ----
@mcp.tool()
def list_custom_fields(product_id: str) -> str:
    """[FREE] List the checkout custom fields on a product (extra info you collect from buyers)."""
    try:
        fields = _get(f"/products/{product_id}/custom_fields").get("custom_fields", [])
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    if not fields:
        return "No custom fields."
    return "Custom fields:\n" + "\n".join(f"  {f.get('name')} · required={f.get('required')} · type={f.get('type','text')}" for f in fields)


@mcp.tool()
def create_custom_field(product_id: str, name: str, required: bool = False) -> str:
    """[FREE] Add a checkout custom field to a product (e.g. 'Discord username')."""
    try:
        _post(f"/products/{product_id}/custom_fields", {"name": name, "required": "true" if required else "false"})
        return f"Added custom field '{name}' (required={required})."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def delete_custom_field(product_id: str, name: str) -> str:
    """[FREE] Remove a checkout custom field from a product by name."""
    try:
        ok = _del(f"/products/{product_id}/custom_fields/{name}").get("success")
        return "Deleted." if ok else "Delete may have failed."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


# ---- Webhooks (resource subscriptions) ----
@mcp.tool()
def list_webhooks(resource_name: str = "sale") -> str:
    """[FREE] List webhook subscriptions for a resource (sale, refund, dispute, cancellation,
    subscription_ended, subscription_restarted, subscription_updated)."""
    try:
        subs = _get("/resource_subscriptions", {"resource_name": resource_name}).get("resource_subscriptions", [])
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"
    if not subs:
        return f"No webhooks for '{resource_name}'."
    return f"Webhooks for '{resource_name}':\n" + "\n".join(f"  {s.get('post_url')} · id={s.get('id')}" for s in subs)


@mcp.tool()
def create_webhook(resource_name: str, post_url: str) -> str:
    """[FREE] Register a webhook: Gumroad POSTs to post_url whenever resource_name fires
    (sale, refund, dispute, cancellation, subscription_ended, etc.)."""
    try:
        r = _put("/resource_subscriptions", {"resource_name": resource_name, "post_url": post_url})
        return f"Webhook created for '{resource_name}' -> {post_url}. id={r.get('resource_subscription',{}).get('id')}"
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


@mcp.tool()
def delete_webhook(subscription_id: str) -> str:
    """[FREE] Delete a webhook subscription by its id."""
    try:
        ok = _del(f"/resource_subscriptions/{subscription_id}").get("success")
        return "Deleted." if ok else "Delete may have failed."
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


# ---- Account ----
@mcp.tool()
def get_account() -> str:
    """[FREE] Your Gumroad account: id, name, email, bio, url. Confirms the token works + who you are."""
    try:
        return _json.dumps(_get("/user").get("user", {}), indent=2, default=str)
    except (ValueError, requests.HTTPError) as e:
        return f"Error: {e}"


if __name__ == "__main__":
    # stdio by default, which is what local MCP clients (Claude Code, Cursor, Claude
    # Desktop) speak. Streamable HTTP only when PORT is set, for hosting. The HTTP mode
    # has no authentication of its own: set HOST=127.0.0.1 to keep it on this machine.
    if os.getenv("PORT"):
        import uvicorn
        uvicorn.run(mcp.streamable_http_app(), host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT")))
    else:
        mcp.run()
