"""FastAPI server for daily-miku-base API."""

import random
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from .raindrop import get_client

app = FastAPI(
    title="daily-miku-base API",
    description="API for daily Miku images from raindrop.io",
    version="0.1.0",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this based on your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "daily-miku-base API",
        "version": "0.1.0",
        "endpoints": {
            "image": "/api/image/{date}",
            "imageFile": "/image/{date}",
            "week": "/api/week/{week}",
            "month": "/api/month/{month}",
            "year": "/api/year/{year}",
            "today": "/today",
            "latest": "/latest",
            "random": "/random",
        },
    }


@app.get("/api/image/{date}")
async def get_image_metadata(date: str):
    """
    Get daily miku metadata for a specific date.
    
    Args:
        date: Date in YYYY-MM-DD format
    
    Returns:
        JSON with image metadata
    """
    client = get_client()
    item = client.get_by_date(date)
    
    if not item:
        raise HTTPException(status_code=404, detail=f"No daily miku found for {date}")
    
    return client.format_response(item, date)


@app.get("/image/{date}")
async def get_image_file(date: str):
    """
    Redirect to the actual image file (Raindrop CDN).
    
    Args:
        date: Date in YYYY-MM-DD format
    
    Returns:
        307 redirect to image URL
    """
    client = get_client()
    item = client.get_by_date(date)
    
    if not item:
        raise HTTPException(status_code=404, detail=f"No image found for {date}")
    
    cover_url = item.get("cover", "")
    if not cover_url:
        raise HTTPException(status_code=404, detail="Image URL not available")
    
    return RedirectResponse(url=cover_url, status_code=307)


@app.get("/api/week/{week}")
async def get_week_images(week: str):
    """
    Get daily miku images for a specific ISO week.
    
    Args:
        week: ISO week in YYYY-W## format (e.g., 2025-W12)
    
    Returns:
        JSON array of 7 images (or fewer if not all days have images)
    """
    try:
        # Parse ISO week format: YYYY-W##
        year_str, week_str = week.split("-W")
        year = int(year_str)
        week_num = int(week_str)
        
        # Get the first day of the ISO week
        # ISO week starts on Monday
        jan_4 = datetime(year, 1, 4)
        week_start = jan_4 - timedelta(days=jan_4.weekday()) + timedelta(weeks=week_num - 1)
        
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid week format. Use YYYY-W## (e.g., 2025-W12)")
    
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
    """
    Get daily miku images for a specific month.
    
    Args:
        month: Month in YYYY-MM format (e.g., 2025-11)
    
    Returns:
        JSON array of images for that month
    """
    try:
        year, month_num = month.split("-")
        year = int(year)
        month_num = int(month_num)
        
        if not (1 <= month_num <= 12):
            raise ValueError("Month must be between 01 and 12")
        
        # Get first and last day of month
        first_day = datetime(year, month_num, 1)
        if month_num == 12:
            last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = datetime(year, month_num + 1, 1) - timedelta(days=1)
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM (e.g., 2025-11)")
    
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
    """
    Get daily miku images for a specific year.
    
    Args:
        year: Year (e.g., 2025)
    
    Returns:
        JSON array of images for that year
    """
    if not (2020 <= year <= 2030):  # Reasonable bounds
        raise HTTPException(status_code=400, detail="Year must be between 2020 and 2030")
    
    client = get_client()
    
    # Fetch all items and filter by year (more efficient than checking each day)
    # Fetch more items to cover the year
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


@app.get("/today")
async def get_today():
    """Redirect to today's image page."""
    today = datetime.now().strftime("%Y-%m-%d")
    return RedirectResponse(url=f"/{today}", status_code=307)


@app.get("/latest")
async def get_latest():
    """Get the most recent daily miku."""
    client = get_client()
    items = client.fetch_raindrops(perpage=1)
    
    if not items:
        raise HTTPException(status_code=404, detail="No images found")
    
    item = items[0]
    created = item.get("created", "")
    if created:
        date = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    else:
        date = datetime.now().strftime("%Y-%m-%d")
    
    return client.format_response(item, date)


@app.get("/random")
async def get_random():
    """Get a random daily miku."""
    client = get_client()
    items = client.fetch_raindrops(perpage=50)
    
    if not items:
        raise HTTPException(status_code=404, detail="No images found")
    
    item = random.choice(items)
    created = item.get("created", "")
    if created:
        date = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    else:
        date = None
    
    return client.format_response(item, date)


@app.get("/api/stats")
async def get_stats():
    """Get statistics about the collection."""
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


@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Custom 404 handler."""
    return JSONResponse(
        status_code=404,
        content={"detail": "Resource not found", "path": str(request.url)},
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Custom 500 handler."""
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
