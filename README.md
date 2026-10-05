# GumroadDNA MCP

The Gumroad API v2 from chat: products, files, sales, refunds, licenses, plus niche scans.

GumroadDNA gives your AI 44 tools over the Gumroad API v2: create a product end to end (file, cover, thumbnail, publish), update, publish and archive products, manage product images, list and refund sales, resend receipts, mark orders shipped, read subscribers, verify and toggle license keys, manage offer codes, custom fields and webhooks, and get a today, week and month revenue snapshot. It also reads the public Gumroad storefront for any keyword (how many products, the price spread, top sellers by rating count) so you can size a niche before you enter it.

Runs locally over stdio with Python 3.10+ and your own Gumroad access token. Free.

Homepage: https://vibedna.ai/store/gumroad

## Tools (44)

| Area | Tools |
|---|---|
| Market research | `scan_gumroad_niche` (public storefront, no token needed) |
| Products | `create_product`, `launch_product`, `update_product`, `publish_product`, `archive_product`, `list_products`, `download_product_files` |
| Files and images | `add_product_file`, `set_product_cover`, `add_product_image`, `list_product_images`, `remove_product_image`, `reorder_product_images`, `download_product_images` |
| Sales | `get_revenue_snapshot`, `list_sales`, `get_sale`, `refund_sale`, `resend_receipt`, `mark_as_shipped` |
| Subscribers | `list_subscribers`, `get_subscriber` |
| License keys | `verify_license`, `enable_license`, `disable_license`, `decrement_license_uses` |
| Discounts and checkout | `list_offer_codes`, `create_offer_code`, `delete_offer_code`, `list_custom_fields`, `create_custom_field`, `delete_custom_field` |
| Stock | `get_stock_status`, `update_stock`, `bump_stock` |
| Webhooks | `list_webhooks`, `create_webhook`, `delete_webhook` |
| Extras | `scan_unlisted_assets` (which of the project names you pass have no listing), `sync_buyers_to_resend` (exports unique buyer emails as a list; it does not call Resend itself) |
| Account and meta | `get_account`, `vibedna_info`, `check_for_update` |

`refund_sale`, `archive_product`, `delete_offer_code`, `delete_webhook` and the other write tools act on your live store. Your AI client asks before calling a tool unless you have allowed it.

## Install

Get a Gumroad access token: app.gumroad.com/settings/advanced > Applications > Create application > Generate access token.

```bash
git clone https://github.com/marstudio360/gumroad-dna-mcp
cd gumroad-dna-mcp
pip install -r requirements.txt
```

The token can live in the MCP entry (below) or in a `.env` file next to `server.py` (copy `.env.example`).

### Claude Code

```bash
claude mcp add gumroad-dna --scope user -e GUMROAD_ACCESS_TOKEN=your_token -- python /absolute/path/to/gumroad-dna-mcp/server.py
```

Or in a project's `.mcp.json`:

```json
{
  "mcpServers": {
    "gumroad-dna": {
      "command": "python",
      "args": ["/absolute/path/to/gumroad-dna-mcp/server.py"],
      "env": { "GUMROAD_ACCESS_TOKEN": "your_token" }
    }
  }
}
```

### Cursor

Add the same `mcpServers` block to `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project).

### Claude Desktop

Add the same `mcpServers` block to `claude_desktop_config.json` (Settings > Developer > Edit Config), then restart Claude Desktop.

[INSTALL.md](./INSTALL.md) is a step-by-step guide written so you can paste it into an AI chat and let the AI do the install.

## Configuration

| Variable | Required | What it does |
|---|---|---|
| `GUMROAD_ACCESS_TOKEN` | Yes (except for `scan_gumroad_niche`) | Your Gumroad API token |
| `PORT` | No | If set, serves streamable HTTP on that port instead of stdio |

## Network

Calls go to `api.gumroad.com` with your token, to `gumroad.com/discover` for niche scans, and to `vibedna.ai/api/mcp/latest` only when you call `check_for_update`.

## License

MIT, see [LICENSE](./LICENSE). Copyright (c) 2026 VibeDNA.

Support: admin@vibedna.ai
