# Plex Manager - Development Roadmap

## Project Vision

Build a unified, self-contained media request and automation system that combines the best aspects of Overseerr with integrated download management. Unlike the traditional stack (Overseerr → Radarr/Sonarr → Prowlarr → qBittorrent), this application handles the entire workflow internally - from user requests through torrent search, download management, and Plex library integration.

**Design Philosophy:** Minimal external dependencies. Integrated workflow from request to media availability.

## Current Status: v1.0 Ready

### ✅ Completed Features (Phases 1-2)

#### Phase 1: Backend Foundation
✅ FastAPI application structure with CORS middleware  
✅ SQLAlchemy database layer with SQLite  
✅ Database auto-initialization on first run  
✅ Complete database models (User, MediaRequest, Download, Season, Settings, etc.)  
✅ Health check and monitoring endpoints  

#### Phase 2: Core Functionality
✅ **Authentication System**
- Plex OAuth integration
- JWT token management with refresh
- Encrypted Plex token storage (Fernet)
- User sessions and permissions
- First user auto-admin (temporary)

✅ **Media Discovery & Search**
- TMDB API integration
- Movie and TV show search
- Trending content (daily/weekly)
- Genre browsing
- Detailed media information
- Poster and backdrop caching

✅ **Request Management**
- Unified request API (movies and TV shows)
- Season-specific TV requests
- Request status tracking
- Duplicate request prevention
- User request history
- Calendar view for upcoming episodes

✅ **Torrent Search & Selection**
- Prowlarr integration (replaced custom torrent search)
- Multi-indexer aggregation
- Weighted scoring algorithm for torrent selection
- Quality preferences (resolution, codec)
- Seeders/leechers consideration
- File size validation

✅ **Download Management**
- qBittorrent API integration
- Automatic torrent addition
- Progress monitoring (real-time)
- Download status tracking
- Failed download retry logic
- Background monitoring with APScheduler
- Stalled download detection

✅ **Retention System**
- Multi-tier deletion policies
- Age-based retention rules
- Watch-based retention rules
- Configurable retention periods
- Audit logging for all deletions
- Manual and automatic cleanup

✅ **User Interface**
- Netflix-style homepage with trending content
- Media details pages with request buttons
- Active downloads dashboard with progress
- Calendar view for TV episodes
- Landing page with Plex OAuth login
- Responsive design for mobile/desktop

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend (HTML/CSS/JS)                       │
│  Landing | Homepage | Media Details | Calendar | Downloads     │
└─────────────────────────────────────────────────────────────────┘
                              ↓ REST API
┌─────────────────────────────────────────────────────────────────┐
│                      Backend (FastAPI)                          │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐  │
│  │ Auth         │ TMDB         │ Request      │ Download     │  │
│  │ (Plex OAuth) │ Integration  │ Management   │ Monitor      │  │
│  └──────────────┴──────────────┴──────────────┴──────────────┘  │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐  │
│  │ Prowlarr     │ qBittorrent  │ Retention    │ Audit        │  │
│  │ Search       │ API Client   │ System       │ Logging      │  │
│  └──────────────┴──────────────┴──────────────┴──────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    ┌─────────────────────┐
                    │  SQLite Database    │
                    │  (SQLAlchemy ORM)   │
                    └─────────────────────┘
```

### External Service Dependencies

**Currently Required:**
- **Plex Media Server** - Media library and OAuth authentication
- **TMDB API** - Movie/TV metadata, search, and images
- **Prowlarr** - Torrent indexer aggregation and search
- **qBittorrent** - Download client with Web UI enabled

---

## Post-v1.0 Development

### Priority 1: Admin & User Management

#### Proper Admin Selection System
**Problem:** Currently, the first user to log in automatically becomes an administrator. This is insecure for multi-user deployments.

**Solution:** Implement proper admin selection mechanism
- Environment variable for designated admin Plex username(s)
- Admin setup wizard on first run
- Manual admin promotion via CLI or config file
- Role-based access control (admin, moderator, user)

**Timeline:** 1-2 weeks

---

### Priority 2: Post-Processing & Plex Integration

#### Automated File Organization
- Extract archived downloads (RAR, ZIP)
- Parse filenames for metadata (title, year, season/episode)
- Match downloaded files to TMDB entries
- Rename files according to Plex naming conventions
- Move files to appropriate library directories
- Trigger Plex library scan after file placement

**Timeline:** 2-3 weeks

---

### Priority 3: Enhanced Monitoring & Reliability

#### Improved Download Handling
- Better stalled download detection
- Automatic alternative torrent selection on failure
- Download bandwidth management
- Disk space monitoring and warnings
- Queue management (pause/resume)

#### Health Monitoring
- Service health checks (Prowlarr, qBittorrent, Plex)
- Automatic reconnection on service failures
- System resource monitoring (CPU, RAM, disk)
- Alert system for critical failures

**Timeline:** 2 weeks

---

### Priority 4: UI/UX Improvements

#### User Experience Enhancements
- Real-time updates via WebSockets
- Toast notifications for events
- Dark/light theme toggle
- Advanced search filters
- User preferences and settings page
- Request approval workflow (optional)
- User request quotas

**Timeline:** 3 weeks

---

### Priority 5: Notification System

#### Multi-Channel Notifications
- Email notifications (SMTP)
- Discord webhook integration
- Telegram bot
- Pushover/Pushbullet support
- In-app notification center

**Notification Events:**
- Request approved
- Download started
- Media available
- Download failed
- Retention cleanup warnings

**Timeline:** 2 weeks

---

### Priority 6: Advanced Features

#### Quality Management
- 4K vs Standard library separation
- Automatic quality upgrades (720p → 1080p)
- Multi-version support (keep both 1080p and 4K)
- Quality profile presets per user

#### Subtitle Integration
- Automatic subtitle download (OpenSubtitles)
- Multi-language subtitle support
- Subtitle file organization

#### Watchlist Sync
- Auto-request from Plex watchlist
- Sync watchlist across users
- Discovery queue recommendations

**Timeline:** 4-5 weeks

---

### Priority 7: Performance & Scalability

#### Database Improvements
- Optional PostgreSQL support for larger deployments
- Database migration system (Alembic)
- Query optimization and indexing
- Database backup automation

#### Caching & Performance
- Redis caching layer
- API response caching
- TMDB metadata pre-fetching
- Image optimization

#### Scalability
- API rate limiting
- Request queuing system
- Background worker separation
- Load balancing support (multi-instance)

**Timeline:** 3-4 weeks

---

### Priority 8: Security Enhancements

#### Authentication Improvements
- Two-factor authentication (2FA)
- API key management for third-party integrations
- Session management improvements
- IP whitelist/blacklist

#### Audit & Logging
- Comprehensive audit trail
- User action logging
- Security event monitoring
- Export audit logs

**Timeline:** 2 weeks

---

### Priority 9: Media Management Enhancements

#### Advanced Retention
- Per-genre retention policies
- User favorites protection
- Collection-based retention
- Watch history integration
- Manual media protection flags

#### Analytics Dashboard
- Media library statistics
- User activity metrics
- Download success rates
- Popular content tracking
- Storage usage analytics

**Timeline:** 2-3 weeks

---

### Priority 10: Production Readiness

#### Deployment
- Docker containerization
- Docker Compose for full stack
- Kubernetes manifests
- Reverse proxy configuration guides
- HTTPS/SSL setup documentation

#### Documentation
- API documentation (OpenAPI/Swagger)
- User guide with screenshots
- Administrator guide
- Troubleshooting wiki
- Development/contribution guide

#### Testing
- Unit test coverage (>70%)
- Integration test suite
- End-to-end test automation
- Performance benchmarking
- Load testing

**Timeline:** 3-4 weeks

---

## Estimated Timeline (Post-v1.0)

| Priority | Feature | Duration |
|----------|---------|----------|
| 1 | Admin Selection System | 1-2 weeks |
| 2 | Post-Processing & Plex Integration | 2-3 weeks |
| 3 | Enhanced Monitoring | 2 weeks |
| 4 | UI/UX Improvements | 3 weeks |
| 5 | Notification System | 2 weeks |
| 6 | Advanced Features | 4-5 weeks |
| 7 | Performance & Scalability | 3-4 weeks |
| 8 | Security Enhancements | 2 weeks |
| 9 | Media Management | 2-3 weeks |
| 10 | Production Readiness | 3-4 weeks |

**Total Estimated Development Time:** 24-30 weeks (6-7 months)

*Note: Priorities can be adjusted based on user feedback and production requirements.*

---

## Success Metrics

### Technical Metrics
- API response time < 500ms (95th percentile)
- Download success rate > 90%
- System uptime > 99.5%
- Database query time < 100ms average

### User Metrics
- Time from request to available < 4 hours
- User satisfaction score > 4.5/5
- Request approval rate > 95%
- Active user retention > 80%

### Quality Metrics
- Zero critical security vulnerabilities
- Test coverage > 70%
- Code review completion rate 100%
- Documentation coverage 100%

---

## Known Limitations (v1.0)

1. **Admin System:** First user automatically becomes admin (insecure for multi-user)
2. **Database:** SQLite only (sufficient for small deployments, not scalable)
3. **No Migrations:** Database auto-initializes (no upgrade path for schema changes)
4. **No Post-Processing:** Downloaded files not automatically organized for Plex
5. **No Notifications:** No user notifications for events
6. **Basic UI:** Functional but minimal user experience features
7. **No Role Management:** All users have same permissions (except admin)

---

## Development Best Practices

### Code Organization
- Keep modules focused on single responsibilities
- Use dependency injection for external services
- Write docstrings for all public functions
- Type hints for all function signatures

### Version Control
- Feature branches for each priority item
- Meaningful commit messages following conventions
- Tag releases (v1.1, v1.2, etc.)
- Keep main branch stable and deployable

### Error Handling
- Graceful degradation when services unavailable
- Detailed error logging with context
- User-friendly error messages
- Automatic retry with exponential backoff

### Security
- Never log sensitive data (API keys, passwords, tokens)
- Use environment variables for all secrets
- Input validation on all user inputs
- Parameterized queries (SQLAlchemy ORM)
- HTTPS enforcement in production

---

*This roadmap is a living document and will be updated as development progresses. Priorities may shift based on user feedback and production requirements.*
