# Requirements

## 1. Functional Requirements

### 1.1 Data Ingestion

The system must fetch image bookmarks from raindrop.io.
- **Sources**:
    - **Twitter**: Primary source. Must handle direct image links or tweet URLs.
    - **Pixiv**: Secondary source. (Note: May require handling user-agent/cookies).
- **Frequency**: Automated daily fetching (e.g., cron job).
- **Metadata**: Capture date added, source URL, tags, and description.

### 1.2 Storage
- Store image files locally or in a dedicated object storage.
- Maintain a database/index of images with their metadata for fast retrieval.

### 1.3 Web Interface

A responsive web application to browse the collection.
- **Views**:
    - **Day View**: Display a single image in full detail.
    - **Week View**: Display 7 images in a horizontal row.
    - **Month View**: Display images in a responsive moodboard/masonry layout.
    - **Year View**: Timeline/strip of all images in a year.
- **Interactions**:
    - **Zoom Transitions**: Smooth, seamless transitions between Day, Week, and Month views (similar to iPhone Photos).
    - **3D Scroll**: Immersive scrolling effects (optional/nice-to-have).
- **URL Access**:
    - `/{YYYY-MM-DD}` → Photo view page
    - `/image/{YYYY-MM-DD}` → Direct image file
    - `/week/{YYYY-W##}`, `/month/{YYYY-MM}`, `/year/{YYYY}` → Time-based views
    - `/today`, `/latest`, `/random`, `/archive` → Special routes
- **API**: RESTful JSON endpoints (`/api/image/{date}`, `/api/search`, etc.)
- **Integration**: Support Obsidian templates via direct image URLs.

### 1.4 Email Automation

- Send a daily email containing the "Miku of the Day".
- Template should be clean and image-focused.

## 2. Non-Functional Requirements

### 2.1 Performance

- **Frontend**: Animations (zooming, scrolling) must run at 60fps.
- **Loading**: Images should load lazily or be optimized for web viewing.

### 2.2 Reliability

- The ingestion and email dispatch process must be robust.
- Failures (e.g., API rate limits) should be logged and retried.

### 2.3 Scalability

- System should handle hundreds to thousands of images without UI lag.

### 2.4 Security & Reliability
- Secure storage of raindrop.io API tokens.
- Handle source link failures (Twitter/Pixiv deletions) gracefully.
- Basic logging and error tracking.

### 2.5 Compatibility

- Modern browsers (Chrome, Firefox, Safari).
- Mobile-responsive with touch gestures.
