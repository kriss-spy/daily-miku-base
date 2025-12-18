"""FastAPI server for daily-miku-base API."""

import os
import random
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from jinja2 import Environment, PackageLoader

from .logging_config import (
    setup_logging,
    generate_request_id,
    set_request_id,
    get_request_id,
)
from .raindrop import get_client, LOCAL_TZ

# Set up logging
logger = setup_logging(os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(
    title="daily-miku-base API",
    description="API for daily Miku images from raindrop.io",
    version="0.1.0",
)

# Set up Jinja2 template environment
template_env = Environment(
    loader=PackageLoader("daily_miku", "templates"),
    autoescape=True,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# REQUEST LOGGING MIDDLEWARE
# ============================================================================


@app.middleware("http")
async def log_request_middleware(request: Request, call_next):
    """Log each request with a unique request ID."""
    # Generate and set request ID
    request_id = generate_request_id()
    set_request_id(request_id)

    # Log incoming request
    logger.info(
        "Request started",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "client": request.client.host if request.client else "unknown",
        },
    )

    try:
        response = await call_next(request)

        # Log response
        logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
            },
        )

        return response
    except Exception as exc:
        # Log error
        logger.error(
            f"Request failed: {str(exc)}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )
        raise


# ============================================================================
# ROOT & API INFO ROUTES (highest priority to avoid path conflicts)
# ============================================================================


@app.get("/")
async def root():
    """Root endpoint - returns JSON API info."""
    return {
        "name": "daily-miku-base API",
        "version": "0.1.0",
        "endpoints": {
            "image": "/api/image/{date}",
            "imageFile": "/image/{date}",
            "week": "/api/week/{week}",
            "month": "/api/month/{month}",
            "year": "/api/year/{year}",
            "today": "/api/today",
            "latest": "/api/latest",
            "random": "/api/random",
            "stats": "/api/stats",
            "htmlPages": {
                "dateImage": "/{date}",
                "today": "/today",
                "latest": "/latest or /latest/page",
                "random": "/random or /random/page",
            },
        },
    }


@app.get("/api/root")
async def api_root():
    """JSON API root endpoint."""
    return {
        "name": "daily-miku-base API",
        "version": "0.1.0",
        "endpoints": {
            "image": "/api/image/{date}",
            "imageFile": "/image/{date}",
            "week": "/api/week/{week}",
            "month": "/api/month/{month}",
            "year": "/api/year/{year}",
            "today": "/api/today",
            "latest": "/api/latest",
            "random": "/api/random",
            "stats": "/api/stats",
        },
    }


# ============================================================================
# SPECIFIC API ROUTES (/api/* paths) - BEFORE generic /{date}
# ============================================================================


@app.get("/api/today")
async def get_today_api():
    """Get today's image (JSON API)."""
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    client = get_client()
    item = client.get_by_date(today)

    if not item:
        logger.info(f"No image found for today ({today})")
        raise HTTPException(status_code=404, detail=f"No daily miku found for {today}")

    logger.debug(f"Retrieved image for today ({today})")
    return client.format_response(item, today)


@app.get("/api/latest")
async def get_latest_api():
    """Get the most recent daily miku (JSON API)."""
    client = get_client()
    items = client.fetch_raindrops(perpage=1)

    if not items:
        raise HTTPException(status_code=404, detail="No images found")

    item = items[0]
    created = item.get("created", "")
    if created:
        date = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime(
            "%Y-%m-%d"
        )
    else:
        date = datetime.now().strftime("%Y-%m-%d")

    return client.format_response(item, date)


@app.get("/latest")
async def get_latest():
    """Get the most recent daily miku (JSON API - alias for /api/latest)."""
    client = get_client()
    items = client.fetch_raindrops(perpage=1)

    if not items:
        raise HTTPException(status_code=404, detail="No images found")

    item = items[0]
    created = item.get("created", "")
    if created:
        date = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime(
            "%Y-%m-%d"
        )
    else:
        date = datetime.now().strftime("%Y-%m-%d")

    return client.format_response(item, date)


@app.get("/api/random")
async def get_random_api():
    """Get a random daily miku (JSON API)."""
    client = get_client()
    items = client.fetch_raindrops(perpage=50)

    if not items:
        raise HTTPException(status_code=404, detail="No images found")

    item = random.choice(items)
    created = item.get("created", "")
    if created:
        date = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime(
            "%Y-%m-%d"
        )
    else:
        date = None

    return client.format_response(item, date)


@app.get("/random")
async def get_random():
    """Get a random daily miku (JSON API - alias for /api/random)."""
    client = get_client()
    items = client.fetch_raindrops(perpage=50)

    if not items:
        raise HTTPException(status_code=404, detail="No images found")

    item = random.choice(items)
    created = item.get("created", "")
    if created:
        date = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime(
            "%Y-%m-%d"
        )
    else:
        date = None

    return client.format_response(item, date)


@app.get("/api/stats")
async def get_stats():
    """Get statistics about the collection (JSON API)."""
    client = get_client()
    items = client.fetch_raindrops(perpage=50)

    if not items:
        return {"total": 0, "dateRange": None, "tags": []}

    dates = []
    all_tags = set()

    for item in items:
        created = item.get("created", "")
        if created:
            dates.append(datetime.fromisoformat(created.replace("Z", "+00:00")))

        tags = item.get("tags", [])
        all_tags.update(tags)

    date_range = None
    if dates:
        dates.sort()
        date_range = {
            "earliest": dates[0].strftime("%Y-%m-%d"),
            "latest": dates[-1].strftime("%Y-%m-%d"),
        }

    return {
        "total": len(items),
        "dateRange": date_range,
        "tags": sorted(list(all_tags)),
    }


@app.get("/api/image/{date}")
async def get_image_metadata(date: str):
    """Get daily miku metadata for a specific date (JSON)."""
    client = get_client()
    item = client.get_by_date(date)

    if not item:
        raise HTTPException(status_code=404, detail=f"No daily miku found for {date}")

    return client.format_response(item, date)


@app.get("/api/week/{week}")
async def get_week_images(week: str):
    """Get daily miku images for a specific ISO week."""
    try:
        year_str, week_str = week.split("-W")
        year = int(year_str)
        week_num = int(week_str)
        jan_4 = datetime(year, 1, 4)
        week_start = (
            jan_4 - timedelta(days=jan_4.weekday()) + timedelta(weeks=week_num - 1)
        )
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=400, detail="Invalid week format. Use YYYY-W## (e.g., 2025-W12)"
        )

    client = get_client()
    images = []

    for day_offset in range(7):
        date = (week_start + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        item = client.get_by_date(date)
        if item:
            images.append(client.format_response(item, date))

    return {"week": week, "count": len(images), "images": images}


@app.get("/api/month/{month}")
async def get_month_images(month: str):
    """Get daily miku images for a specific month."""
    try:
        year, month_num = month.split("-")
        year = int(year)
        month_num = int(month_num)

        if not (1 <= month_num <= 12):
            raise ValueError("Month must be between 01 and 12")

        first_day = datetime(year, month_num, 1)
        if month_num == 12:
            last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = datetime(year, month_num + 1, 1) - timedelta(days=1)

    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid month format. Use YYYY-MM (e.g., 2025-11)"
        )

    client = get_client()
    images = []

    current_day = first_day
    while current_day <= last_day:
        date = current_day.strftime("%Y-%m-%d")
        item = client.get_by_date(date)
        if item:
            images.append(client.format_response(item, date))
        current_day += timedelta(days=1)

    return {"month": month, "count": len(images), "images": images}


@app.get("/api/year/{year}")
async def get_year_images(year: int):
    """Get daily miku images for a specific year."""
    if not (2020 <= year <= 2030):
        raise HTTPException(
            status_code=400, detail="Year must be between 2020 and 2030"
        )

    client = get_client()
    all_items = client.fetch_raindrops(perpage=50)

    images = []
    for item in all_items:
        created = item.get("created", "")
        if created:
            item_date = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if item_date.year == year:
                date_str = item_date.strftime("%Y-%m-%d")
                images.append(client.format_response(item, date_str))

    return {"year": year, "count": len(images), "images": images}


# ============================================================================
# IMAGE FILE REDIRECT ROUTES
# ============================================================================


@app.get("/image/{date}")
async def get_image_file(date: str):
    """Redirect to the actual image file (Raindrop CDN)."""
    client = get_client()
    item = client.get_by_date(date)

    if not item:
        raise HTTPException(status_code=404, detail=f"No image found for {date}")

    cover_url = item.get("cover", "")
    if not cover_url:
        raise HTTPException(status_code=404, detail="Image URL not available")

    return RedirectResponse(url=cover_url, status_code=307)


# ============================================================================
# SPECIAL HTML ROUTES (before generic /{date})
# ============================================================================


@app.get("/today")
async def get_today_html():
    """Redirect to today's image page."""
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    return RedirectResponse(url=f"/{today}", status_code=307)


@app.get("/latest/page", response_class=HTMLResponse)
async def get_latest_page():
    """Display the most recent daily miku."""
    client = get_client()
    items = client.fetch_raindrops(perpage=1)

    if not items:
        template = template_env.get_template("image.html")
        return template.render(
            image=None, date="latest", prev_date=None, next_date=None
        )

    item = items[0]
    created = item.get("created", "")
    if created:
        date = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime(
            "%Y-%m-%d"
        )
    else:
        date = datetime.now().strftime("%Y-%m-%d")

    image_data = client.format_response(item, date)

    template = template_env.get_template("image.html")
    return template.render(image=image_data, date=date, prev_date=None, next_date=None)


@app.get("/random/page", response_class=HTMLResponse)
async def get_random_page():
    """Display a random daily miku."""
    client = get_client()
    items = client.fetch_raindrops(perpage=50)

    if not items:
        template = template_env.get_template("image.html")
        return template.render(
            image=None, date="random", prev_date=None, next_date=None
        )

    item = random.choice(items)
    created = item.get("created", "")
    if created:
        date = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime(
            "%Y-%m-%d"
        )
    else:
        date = None

    image_data = client.format_response(item, date)

    template = template_env.get_template("image.html")
    return template.render(
        image=image_data, date=date or "random", prev_date=None, next_date=None
    )


# ============================================================================
# GENERIC HTML ROUTE (lowest priority to avoid shadowing specific routes)
# ============================================================================


@app.get("/{date}", response_class=HTMLResponse)
async def get_image_page(date: str):
    """Display image page for a specific date."""
    client = get_client()
    item = client.get_by_date(date)

    if not item:
        template = template_env.get_template("image.html")
        return template.render(image=None, date=date, prev_date=None, next_date=None)

    image_data = client.format_response(item, date)

    # Calculate prev/next dates
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        prev_date = (date_obj - timedelta(days=1)).strftime("%Y-%m-%d")
        next_date = (date_obj + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        prev_date = None
        next_date = None

    template = template_env.get_template("image.html")
    return template.render(
        image=image_data, date=date, prev_date=prev_date, next_date=next_date
    )


# ============================================================================
# ERROR HANDLERS
# ============================================================================

# Let HTTPException from endpoints pass through with their own messages


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with request ID."""
    logger.warning(
        f"HTTP exception: {exc.detail}",
        extra={
            "request_id": get_request_id(),
            "status_code": exc.status_code,
            "path": request.url.path,
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "request_id": get_request_id(),
            "path": str(request.url.path),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions with request ID and logging."""
    request_id = get_request_id()

    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {str(exc)}",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "error_type": type(exc).__name__,
        },
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": request_id,
            "path": str(request.url.path),
            "error_type": type(exc).__name__,
        },
    )
