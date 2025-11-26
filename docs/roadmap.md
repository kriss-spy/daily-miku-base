# Roadmap

## Project Vision

daily-miku-base is a comprehensive system for discovering, displaying, and sharing daily Miku artwork from Twitter and Pixiv through raindrop.io bookmarks.

## Milestones

### Phase 1: Backend & CLI (MVP)

**Goal**: Functional server with API and CLI for daily tasks

**Features**:
- ✅ Documentation and architecture design
- ⬜ Raindrop.io API client implementation
  - Fetch bookmarks by tag (`#daily-miku`)
  - Filter by date
  - Handle authentication and rate limiting
- ⬜ CLI commands
  - `fetch-today` — Get today's daily miku
  - `fetch-date <YYYY-MM-DD>` — Get specific date
  - `send-email` — Send daily email
  - `test-connection` — Verify raindrop.io setup
- ⬜ Core API endpoints
  - `GET /api/image/{date}` — JSON metadata
  - `GET /image/{date}` — Redirect to image file
  - `GET /api/week/{week}` — Weekly images
  - `GET /api/month/{month}` — Monthly images
- ⬜ Email automation
  - HTML email template with image embed
  - SMTP configuration
  - GitHub Actions daily workflow
- ⬜ Error handling and logging
- ⬜ Unit tests for core functionality

**Status**: Documentation complete, ready to code

### Phase 2: Basic Web UI

**Goal**: Simple web interface for browsing images

**Features**:
- ⬜ Single-page photo view (`/{date}`)
  - Display image with metadata
  - Source link, title, description
  - Navigation (prev/next day)
- ⬜ Special routes
  - `/today` — Today's image
  - `/latest` — Most recent image
  - `/random` — Random image
- ⬜ Basic styling and responsive layout
- ⬜ Mobile-friendly design

### Phase 3: Time-based Views

**Goal**: Multiple view modes for different time scales

**Features**:
- ⬜ Week view (`/week/{YYYY-W##}`)
  - 7 images in horizontal row
  - Scroll navigation
- ⬜ Month view (`/month/{YYYY-MM}`)
  - Calendar grid layout
  - Responsive masonry/moodboard
- ⬜ Year view (`/year/{YYYY}`)
  - Timeline/strip visualization
  - Smooth scrolling
- ⬜ Archive view (`/archive`)
  - Infinite scroll or pagination
  - All images chronologically

### Phase 4: Advanced UI & Interactions

**Goal**: Fancy view transitions and 3D effects

**Features**:
- ⬜ Smooth zoom transitions between views
  - Day ↔ Week ↔ Month ↔ Year
  - iPhone Photos-style animations
- ⬜ 3D scroll effects
  - Inspired by 初音ミクの激唱
  - Immersive parallax scrolling
- ⬜ Deep zoom functionality
  - High-resolution image viewing
- ⬜ Touch gestures for mobile
  - Pinch to zoom
  - Swipe navigation
- ⬜ Performance optimization
  - Lazy loading
  - Image preloading
  - 60fps animations

### Phase 5: Search & Discovery

**Goal**: Find specific images and explore by tags

**Features**:
- ⬜ Search functionality
  - `GET /api/search?q={query}`
  - Search by title, description, tags
- ⬜ Tag filtering
  - Browse images by additional tags
  - `GET /api/tags` — List all tags
- ⬜ Statistics dashboard
  - `GET /api/stats`
  - Total images, date range, tags
- ⬜ Advanced filters
  - By source (Twitter/Pixiv)
  - By date range

### Phase 6: Deployment & Production

**Goal**: Live production deployment

**Features**:
- ⬜ Vercel deployment
  - Frontend + API on Vercel
  - Environment variables configured
- ⬜ Domain setup
  - `dailymiku.dev` DNS configured
  - SSL certificate (automatic via Vercel)
- ⬜ GitHub Actions workflows
  - Daily email cron job
  - Automated testing on PR
- ⬜ Monitoring and logging
  - Uptime monitoring
  - Error tracking
  - Performance metrics
- ⬜ Documentation updates
  - Production setup guide
  - Troubleshooting section

## Future Enhancements (Post-MVP)

### Optional Features
- **Image caching**: Local storage fallback (Vercel Blob/R2)
- **Permanent copy automation**: Bulk enable for existing bookmarks
- **Multiple themes**: Dark mode, custom color schemes
- **Social sharing**: Share specific dates on Twitter
- **API rate limiting**: Protect backend from abuse
- **RSS feed**: Subscribe to daily miku updates
- **Webhook support**: Notify on new images
- **Collection management**: Organize into custom collections
- **User accounts**: Personalized favorites and history
- **Comments/reactions**: Community engagement

### Technical Improvements
- **Caching layer**: Redis for frequently accessed data
- **CDN optimization**: Edge caching for static assets
- **Database**: PostgreSQL for local metadata storage
- **GraphQL API**: Alternative to REST
- **WebSocket**: Real-time updates
- **Progressive Web App**: Offline support

## Timeline (Tentative)

- **Phase 1 (MVP)**: 1-2 weeks
- **Phase 2 (Basic UI)**: 1 week
- **Phase 3 (Time views)**: 1-2 weeks
- **Phase 4 (Advanced UI)**: 2-3 weeks
- **Phase 5 (Search)**: 1 week
- **Phase 6 (Production)**: 1 week

**Total estimated**: 2-3 months for full feature set

## Notes

- Backend-only (Phase 1) is sufficient for personal use
- Frontend phases can be developed incrementally
- Advanced UI features (Phase 4) are nice-to-have
- Focus on stability and performance over feature completeness
