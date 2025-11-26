# Raindrop.io API Reference

Official documentation: [developer.raindrop.io](https://developer.raindrop.io/)  
GitHub repo: [raindropio/developer-site](https://github.com/raindropio/developer-site)

## Authentication

**Test Token** (for personal use):
1. Go to [App Management](https://app.raindrop.io/settings/integrations)
2. Create a new app → Get "Test Token"
3. Set as environment variable: `RAINDROP_TOKEN=your_token_here`

**API Request Header**:
```http
Authorization: Bearer YOUR_TEST_TOKEN
```

## Base URL

```
https://api.raindrop.io/rest/v1
```

## Key Endpoints for Daily Miku

### 1. Get Raindrops by Tag

Fetch all bookmarks tagged with `#daily-miku`:

```http
GET /raindrops/0?search=%23daily-miku&perpage=50&sort=-created
```

**Query Parameters**:
- `search=%23daily-miku` — Filter by tag (URL-encoded `#daily-miku`)
- `perpage=50` — Results per page (max 50)
- `sort=-created` — Sort by creation date (newest first)
- `page=0` — Pagination (0-indexed)

**Response** (JSON):
```json
{
  "result": true,
  "items": [
    {
      "_id": 123456789,
      "title": "Daily Miku Artwork",
      "excerpt": "Beautiful Miku illustration",
      "note": "",
      "cover": "https://up.raindrop.io/raindrop/thumbs/123/456/789.png",
      "link": "https://twitter.com/artist/status/1234567890",
      "tags": ["daily-miku", "hatsune-miku"],
      "created": "2025-11-26T08:30:00.000Z",
      "domain": "twitter.com",
      "type": "link"
    }
  ],
  "count": 1,
  "collectionId": 0
}
```

**Key Fields**:
- `_id` — Raindrop unique ID
- `cover` — Image URL (use this as the daily miku image)
- `link` — Original source URL (Twitter/Pixiv post)
- `created` — ISO 8601 timestamp
- `tags` — Array of tags

### 2. Get Single Raindrop

Fetch a specific bookmark by ID:

```http
GET /raindrop/{raindropId}
```

**Example**:
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://api.raindrop.io/rest/v1/raindrop/123456789
```

### 3. Search Raindrops by Date

To find the daily miku for a specific date, search by tag and filter by `created` date in your code:

```python
# Pseudocode
response = get_raindrops(tag="daily-miku", sort="-created", perpage=50)
target_date = "2025-11-26"
for item in response["items"]:
    created_date = parse_iso(item["created"]).date()
    if created_date == target_date:
        return item
```

### 4. Get Collections (Optional)

If you organize daily-miku bookmarks in a specific collection:

```http
GET /collections
```

Then filter by collection ID instead of tag:
```http
GET /raindrops/{collectionId}?sort=-created&perpage=50
```

## Image Handling

**Cover Image**:
- Raindrop provides a `cover` field with a CDN URL
- Format: `https://up.raindrop.io/raindrop/thumbs/{path}.png`
- Usually optimized/thumbnailed by Raindrop
- **Note**: Not a permanent copy unless you enable "Permanent Copy" in Raindrop settings

**Permanent Copy**:
- In Raindrop settings, enable "Permanent library" to cache original images
- Otherwise, if the source (Twitter/Pixiv) deletes the post, the image may become unavailable

**Pixiv Images**:
- Pixiv URLs often require referer headers and cookies
- Raindrop's `cover` should work even for Pixiv (Raindrop handles it)
- If you need to fetch the original Pixiv image yourself, see `architecture.md` notes

## Rate Limits

- **Free Plan**: 120 requests/minute
- **Pro Plan**: Higher limits (check official docs)
- Implement exponential backoff for `429 Too Many Requests`

## Error Handling

Common errors:
- `401 Unauthorized` — Invalid token
- `404 Not Found` — Raindrop ID doesn't exist
- `429 Too Many Requests` — Rate limit exceeded

## Example Python Code

```python
import requests
from datetime import datetime

RAINDROP_TOKEN = "your_token_here"
BASE_URL = "https://api.raindrop.io/rest/v1"

def get_daily_miku(date_str: str) -> dict:
    """
    Fetch daily miku for a given date (YYYY-MM-DD)
    """
    headers = {"Authorization": f"Bearer {RAINDROP_TOKEN}"}
    params = {
        "search": "#daily-miku",
        "perpage": 50,
        "sort": "-created"
    }
    
    response = requests.get(f"{BASE_URL}/raindrops/0", headers=headers, params=params)
    response.raise_for_status()
    
    target_date = datetime.fromisoformat(date_str).date()
    
    for item in response.json()["items"]:
        created_date = datetime.fromisoformat(item["created"].replace("Z", "+00:00")).date()
        if created_date == target_date:
            return {
                "date": date_str,
                "imageUrl": item["cover"],
                "sourceUrl": item["link"],
                "title": item["title"],
                "description": item["excerpt"],
                "tags": item["tags"],
                "raindropId": item["_id"],
                "timestamp": item["created"]
            }
    
    return None
```

## Storage Notes

See `architecture.md` for why Raindrop.io was chosen over GitHub repo storage.

**Pros**:
- Centralized bookmark management
- IFTTT integration for automated saving
- Built-in image caching (with permanent copy enabled)
- Tags and metadata built-in

**Cons**:
- Dependent on Raindrop.io service availability
- Free tier rate limits
- Image URLs may break if original source deleted (unless permanent copy enabled)
