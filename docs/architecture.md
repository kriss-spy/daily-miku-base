# Architecture

## System Overview

daily-miku-base is a multi-functional system that:

1. Fetches daily image bookmarks from raindrop.io (tagged with `#daily-miku`)
2. Processes and serves these images via a web interface with multiple view modes
3. Sends daily email notifications with the featured image

## Tech Stack

- **Image Source**: IFTTT (triggers) → raindrop.io (storage/bookmarks)
- **Backend**: Python server (fetch, process, serve raindrop.io API)
- **Frontend**: Web UI with multiple view modes (photo, day, month, year views)
- **Email**: Daily email sender (configured via email-automation.md)
- **Database/Storage**: raindrop.io API (primary source of truth)

## Data Flow

```
[Twitter/Pixiv] 
    ↓ (user save)
[IFTTT] → [raindrop.io] (#daily-miku tag)
    ↓
[Backend Server] (fetch via raindrop.io API)
    ├→ [Email Service] (send daily)
    └→ [Web UI] (display with multiple layouts)
```

## Components

### 1. Image Source & Ingestion

- **IFTTT**: Automated triggers that save posts to raindrop.io
- **raindrop.io API**: Stores bookmarks + cover images
  - Bookmark title, description, URL
  - Embedded image (if available on the post)
  - Tags (filter by `#daily-miku`)
  - Timestamp/date metadata

### 2. Backend Server

- **Raindrop API Client**: Fetch bookmarks tagged `#daily-miku`
- **Image Processor**: Handle Twitter/Pixiv image URLs
  - Twitter: Direct image URL access
  - Pixiv: Requires user-agent + cookies; image URLs change frequently
- **Scheduler**: Daily task to fetch and process
- **API Endpoint**: Serve image data + metadata to frontend

#### URL Schema

Base domain: `https://dailymiku.dev`

**Image Files (Direct Access)**

- `GET /image/{YYYY-MM-DD}` → Direct image file (JPEG/PNG)
  - Example: `/image/2025-11-26` → returns the image file itself
  - Content-Type: `image/jpeg` or `image/png`
  - Suitable for embedding, Obsidian templates, etc.

**Web Views (HTML Pages)**

- `GET /` → Homepage (today's image or latest)
- `GET /{YYYY-MM-DD}` → Photo view (single image with details)
  - Example: `/2025-11-26` → page showing Nov 26, 2025 image
- `GET /day/{YYYY-MM-DD}` → Day view (alternative explicit path)

**Time-based Views**

- `GET /week/{YYYY-W##}` → Week view (7 images in that ISO week)
  - Example: `/week/2025-W12` → March 17-23, 2025
- `GET /month/{YYYY-MM}` → Month view (calendar grid)
  - Example: `/month/2025-11` → November 2025
- `GET /year/{YYYY}` → Year view (timeline/strip)
  - Example: `/year/2025` → all 2025 images

**Special Views**

- `GET /today` → Redirect to today's date
- `GET /latest` → Most recent image
- `GET /random` → Random image from archive
- `GET /archive` → Browse all images (infinite scroll or pagination)

**API Endpoints (JSON)**

- `GET /api/image/{YYYY-MM-DD}` → JSON metadata + image URL
- `GET /api/week/{YYYY-W##}` → JSON array of 7 images
- `GET /api/month/{YYYY-MM}` → JSON array of images in month
- `GET /api/year/{YYYY}` → JSON array of images in year
- `GET /api/search?q={query}` → Search by title/tag/description
- `GET /api/tags` → List all tags
- `GET /api/stats` → Statistics (total images, date range, etc.)

**Response Format (API JSON)**

```json
{
  "date": "2025-11-26",
  "imageUrl": "https://dailymiku.dev/image/2025-11-26",
  "sourceUrl": "https://twitter.com/user/status/123456",
  "title": "Daily Miku #1234",
  "description": "Beautiful artwork by @artist",
  "tags": ["daily-miku", "hatsune-miku"],
  "raindropId": "123456789",
  "timestamp": "2025-11-26T08:00:00Z"
}
```

### 3. Frontend/Web UI

Multiple view modes (refer to iphone Photos paradigm):

- **Photo View**: Single image, detail view (source, date, description)
- **Day View**: Images grouped by day
- **Month View**: Calendar grid of images per month
- **Year View**: Timeline/strip of images per year
- **Smooth Transitions**: Zoom/pan animations between views
- **Deep Zoom**: 3D scrolling effect (inspired by 初音ミクの激唱)

### 4. Email Service

- **Daily Scheduler**: Trigger once per day
- **Template**: HTML email with image embed + metadata
- **Delivery**: Send to configured recipient(s)
- See [email-automation guide](email-automation.md) for setup

## original basic design

### from where

images are mainly from twitter
usually with source url

sometimes from pixiv
which is annoying
cuz pixiv require user-agent, cookies to view or download image directly
no matter is the image NSFW or not

don't consider other sources for now

### how to display daily miku image

raindrop.io already have some layouts like list, cards, headlines, moodboard(awesome, responsive)
but since it's a website, I expect some crazy effects
basically the data is linear

refer to iphone Photos
photo view
day view
month view
year view
smooth switch by zooming

deep zoom

would wanna a smooth 3d scroll
like that in 初音ミクの激唱

### daily miku email

refer [the guide](email-automation.md)
