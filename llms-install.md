# GumroadDNA: Install

44 tools for the Gumroad API v2, no browser: products (create + upload + cover + publish + archive + download), sales (list + refund + resend receipt + mark shipped), customers/subscribers, licenses (verify/enable/disable), discount codes, custom fields, webhooks, account. Plus a few extras: a niche scan of the public Gumroad storefront, a buyer email export, and a check of which of your project names have no listing yet. Free, runs locally.

## Requirements

- Python 3.10+
- A Gumroad access token: app.gumroad.com/settings/advanced > Applications > Create application > Generate access token

## Install

```bash
# 1. get the code and install deps
git clone https://github.com/marstudio360/gumroad-dna-mcp
cd gumroad-dna-mcp
pip install -r requirements.txt

# 2. set your token (export it, or put it in a .env file next to server.py)
cp .env.example .env    # then edit .env and paste your token

# 3. add it to your MCP client (Claude Code shown)
claude mcp add gumroad-dna --scope user -- python /absolute/path/to/gumroad-dna-mcp/server.py

# 4. close and reopen your Claude Code tab so the MCP loads
```

Or add the entry to a project's `.mcp.json` by hand:

```json
{
  "mcpServers": {
    "gumroad-dna": {
      "command": "python",
      "args": ["/absolute/path/to/gumroad-dna-mcp/server.py"],
      "env": { "GUMROAD_ACCESS_TOKEN": "your_token_here" }
    }
  }
}
```

## The fast way (let Claude do it)

Open a Claude Code session in the cloned (or unzipped) folder and tell Claude:

> "Install this GumroadDNA MCP. Run pip install -r requirements.txt, help me create a .env with my GUMROAD_ACCESS_TOKEN, then add the MCP entry pointing to the absolute path of server.py. Close and reopen the tab when done."

## Verify

In a fresh Claude Code session:

> "Show my Gumroad revenue snapshot for the last 30 days"

Claude should call `get_revenue_snapshot` and return live numbers.

## The 44 tools

**Research a market, even one you are not in yet:**
`scan_gumroad_niche` reads the public storefront for any keyword: how many products exist, the
price spread, and the top sellers by rating count. No account needed for this one.

**Products:**
`create_product` (end to end: file, cover, thumbnail, publish) · `launch_product` · `update_product` ·
`publish_product` · `archive_product` (reversible) · `list_products` · `download_product_files`

**Files and images:**
`add_product_file` (multipart, any size) · `set_product_cover` · `add_product_image` ·
`list_product_images` · `remove_product_image` · `reorder_product_images` (the first one becomes
the main cover) · `download_product_images`

**Sales:**
`get_revenue_snapshot` (today, week, month) · `list_sales` (filter by date, product or buyer,
paginated) · `get_sale` · `refund_sale` (full or partial) · `resend_receipt` · `mark_as_shipped`

**Subscribers:**
`list_subscribers` · `get_subscriber` (status, billing period, charges, cancellation)

**Licence keys:**
`verify_license` (optionally counting a seat) · `enable_license` · `disable_license` ·
`decrement_license_uses`

**Discounts and checkout:**
`list_offer_codes` · `create_offer_code` (percent or fixed, with or without a use limit) ·
`delete_offer_code` · `list_custom_fields` · `create_custom_field` · `delete_custom_field`

**Scarcity:**
`get_stock_status` · `update_stock` · `bump_stock` (keeps N copies "left" on every limited
product, skipping the unlimited ones)

**Webhooks, so a purchase can trigger delivery elsewhere:**
`list_webhooks` · `create_webhook` · `delete_webhook`

**Extras:**
`scan_unlisted_assets` (pass a list of your project names; it returns the ones with no Gumroad listing) ·
`sync_buyers_to_resend` (exports unique buyer emails, first names and products as a list you can
import into an email tool such as Resend; it does not call Resend itself) ·
`get_account` · `vibedna_info` · `check_for_update`

Creating and editing products needs the paid Gumroad tier. Everything else, including sales,
licences, discounts, stock and webhooks, works on the free one.

## Trouble

- "GUMROAD_ACCESS_TOKEN not set": step 2 above; restart the tab after adding .env
- MCP doesn't appear: close and reopen the tab; the MCP list loads at session start
- 401 from Gumroad: token revoked or wrong scope; regenerate at app.gumroad.com/settings/advanced

## Support

admin@vibedna.ai · https://vibedna.ai/store/gumroad

License: MIT.

VibeDNA, 2026
