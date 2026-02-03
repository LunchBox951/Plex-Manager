# Plex Manager Setup Guide

## Overview

Plex Manager is a unified media request and automation system that integrates with Plex, TMDB, Prowlarr, and qBittorrent to provide a Netflix-style interface for requesting and managing media.

## Prerequisites

- **Python 3.8+**
- **Plex Media Server** (for OAuth authentication and media library)
- **TMDB API Key** (free account at https://www.themoviedb.org/settings/api)
- **Prowlarr** (for torrent indexer aggregation)
- **qBittorrent** (with Web UI enabled)

---

## Part 1: Initial Setup

### Step 1: Install Python Dependencies

```bash
# Activate your virtual environment
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1

# On Linux/Mac:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Generate Security Keys

Run these commands to generate required security keys:

```bash
# Generate SECRET_KEY (for session management)
python -c "import secrets; print(f'SECRET_KEY={secrets.token_urlsafe(32)}')"

# Generate JWT_SECRET_KEY (for JWT tokens)
python -c "import secrets; print(f'JWT_SECRET_KEY={secrets.token_urlsafe(32)}')"

# Generate PLEX_CLIENT_ID (for OAuth)
python -c "import uuid; print(f'PLEX_CLIENT_ID={uuid.uuid4()}')"

# Generate ENCRYPTION_KEY (for token encryption)
python -c "from cryptography.fernet import Fernet; print(f'ENCRYPTION_KEY={Fernet.generate_key().decode()}')"
```

### Step 3: Create .env File

1. Copy `.env.example` to `.env`:
   ```bash
   # Windows PowerShell
   Copy-Item .env.example .env
   
   # Linux/Mac
   cp .env.example .env
   ```

2. Open `.env` and fill in all required values (see Part 2-4 for service-specific setup)

---

## Part 2: External Service Setup

### A. Plex Media Server

#### Get Your Plex Server URL

Your Plex server URL is typically:
- **Local network**: `http://192.168.x.x:32400`
- **Localhost**: `http://localhost:32400`

To find it:
1. Open Plex Web App (app.plex.tv)
2. Go to Settings → Network
3. Note the server address and port (default: 32400)

#### Get Your Plex Token

**Method 1: Through Plex Web App**
1. Sign in to app.plex.tv
2. Open any media item
3. Click "..." → "Get Info" → "View XML"
4. Find `X-Plex-Token=XXXXX` in the URL
5. Copy the token value

**Method 2: Through PlexPass (easier)**
1. Go to https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/
2. Follow the instructions for your platform

#### Update .env
```env
PLEX_URL=http://192.168.1.100:32400
PLEX_TOKEN=your-plex-token-here
```

---

### B. TMDB API

1. Create a free account at https://www.themoviedb.org/signup
2. Go to https://www.themoviedb.org/settings/api
3. Request an API key (fill out the form with your app info)
4. Copy the **API Key (v3 auth)**

#### Update .env
```env
TMDB_API_KEY=your-tmdb-api-key-here
```

---

### C. Prowlarr Setup

Prowlarr aggregates multiple torrent indexers into a single API.

#### Installation

**Windows:**
1. Download from https://prowlarr.com/#downloads
2. Run the installer
3. Prowlarr starts on http://localhost:9696

**Linux (Docker):**
```bash
docker run -d \
  --name=prowlarr \
  -p 9696:9696 \
  -v /path/to/config:/config \
  --restart unless-stopped \
  lscr.io/linuxserver/prowlarr:latest
```

#### Configuration

1. Open Prowlarr at http://localhost:9696
2. **Add Indexers:**
   - Go to Indexers → Add Indexer
   - Add your preferred indexers (1337x, RARBG, The Pirate Bay, etc.)
   - Configure each indexer with required credentials/cookies
3. **Get API Key:**
   - Go to Settings → General → Security
   - Copy the API Key

#### Update .env
```env
PROWLARR_URL=http://localhost:9696
PROWLARR_API_KEY=your-prowlarr-api-key-here
```

---

### D. qBittorrent Setup

qBittorrent is the download client for torrents.

#### Installation

**Windows:**
1. Download from https://www.qbittorrent.org/download.php
2. Run the installer
3. Launch qBittorrent

**Linux (Docker):**
```bash
docker run -d \
  --name=qbittorrent \
  -p 8080:8080 \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  --restart unless-stopped \
  lscr.io/linuxserver/qbittorrent:latest
```

#### Enable Web UI

1. Open qBittorrent application
2. Go to Tools → Options → Web UI
3. **Enable the Web User Interface**
4. Set Port: `8080` (default)
5. Set Username: `admin` (or custom)
6. Set Password: (choose a strong password)
7. Click "Save"

#### Test Web UI
- Open http://localhost:8080
- Login with your username/password
- You should see the qBittorrent Web UI

#### Update .env
```env
QBITTORRENT_URL=http://localhost:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=your-password-here
```

---

## Part 3: Directory Structure

Plex Manager needs paths for downloads and media libraries.

### Create Required Directories

**Windows PowerShell:**
```powershell
# Create directories
New-Item -ItemType Directory -Force -Path "C:\downloads"
New-Item -ItemType Directory -Force -Path "C:\plex\movies"
New-Item -ItemType Directory -Force -Path "C:\plex\tv"
```

**Linux/Mac:**
```bash
mkdir -p /downloads
mkdir -p /plex/movies
mkdir -p /plex/tv
```

### Update .env
```env
DOWNLOADS_PATH=C:\downloads          # Windows
# DOWNLOADS_PATH=/downloads          # Linux/Mac

MOVIES_PATH=C:\plex\movies           # Windows
# MOVIES_PATH=/plex/movies           # Linux/Mac

TV_PATH=C:\plex\tv                   # Windows
# TV_PATH=/plex/tv                   # Linux/Mac
```

**Note:** These paths should match your Plex library paths or be accessible to Plex for scanning.

---

## Part 4: Complete .env Configuration

Your final `.env` file should contain all these variables:

```env
# Security Keys (generated in Step 2)
SECRET_KEY=your-generated-secret-key
JWT_SECRET_KEY=your-generated-jwt-secret-key
PLEX_CLIENT_ID=your-generated-uuid
ENCRYPTION_KEY=your-generated-fernet-key

# Database
DATABASE_URL=sqlite:///./data/plex_manager.db

# Plex Configuration
PLEX_URL=http://192.168.1.100:32400
PLEX_TOKEN=your-plex-token

# TMDB API
TMDB_API_KEY=your-tmdb-api-key

# Prowlarr
PROWLARR_URL=http://localhost:9696
PROWLARR_API_KEY=your-prowlarr-api-key

# qBittorrent
QBITTORRENT_URL=http://localhost:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=your-qbittorrent-password

# File Paths
DOWNLOADS_PATH=C:\downloads
MOVIES_PATH=C:\plex\movies
TV_PATH=C:\plex\tv

# Environment
ENV=development
```

---

## Part 5: Launch the Application

### Start the Application

```bash
python main.py
```

The application will:
- Initialize the SQLite database (auto-creates tables)
- Start the FastAPI web server on http://localhost:8000
- Display startup logs
- Start the background download monitor

### Verify Startup

Check the console for:
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

## Part 6: First Login & Admin Setup

### Access the Application

1. Open your browser to http://localhost:8000
2. You'll see the landing page with "Sign in with Plex"
3. Click the button to start Plex OAuth flow
4. Authenticate with your Plex account
5. Authorize the application

### ⚠️ Important: First User Becomes Admin

**The first user to login automatically becomes an administrator.**

- This is a temporary security measure for v1.0
- Subsequent users will have standard user permissions
- Admin selection improvements are planned for future releases

### Admin Capabilities

As an admin, you have access to:
- All user requests and downloads
- Retention system management
- System monitoring and logs
- Download retry/management
- (Future: User management, settings configuration)

---

## Part 7: Using Plex Manager

### For Users

1. **Search for Media:**
   - Use the search bar on the homepage
   - Browse trending movies/TV shows
   - Click any media item for details

2. **Request Media:**
   - Click the "Request" button on any media details page
   - For TV shows: Select specific seasons or request all
   - Request is auto-approved and download starts immediately

3. **Track Requests:**
   - View your request history on the homepage
   - See download progress in real-time
   - Get notified when media is available (future feature)

4. **Calendar:**
   - View upcoming TV episodes
   - See release dates for requested shows

### Request Status Flow

1. **Pending** → Request submitted
2. **Searching** → Looking for torrents via Prowlarr
3. **Downloading** → Torrent active in qBittorrent
4. **Processing** → Download complete, processing files (future)
5. **Available** → Media ready in Plex library
6. **Failed** → Something went wrong (admin can retry)

---

## Part 8: System Architecture

### How It Works

```
User Request (Homepage)
    ↓
TMDB API (metadata & images)
    ↓
Prowlarr (search torrents)
    ↓
Scoring Algorithm (select best torrent)
    ↓
qBittorrent (download torrent)
    ↓
Background Monitor (track progress)
    ↓
Retention System (cleanup old media)
    ↓
Plex Library (media available)
```

### Automatic Processes

**Download Monitor** (runs every 60 seconds):
- Updates download progress
- Detects completed downloads
- Retries failed downloads
- Detects stalled torrents

**Retention System** (configurable schedule):
- Age-based cleanup rules
- Watch-based cleanup rules
- Multi-tier retention policies
- Audit logging for all deletions

---

## Troubleshooting

### Missing Environment Variables Error

**Error:** `ERROR: Missing required environment variables`

**Solution:**
- Verify `.env` file exists in project root
- Check all required variables are set (see Part 4)
- Restart the application after updating `.env`

### Database Errors

**Error:** `Table already exists` or initialization errors

**Solution:**
```bash
# Stop the application
# Delete the database file
Remove-Item data\plex_manager.db  # Windows
# rm data/plex_manager.db         # Linux/Mac

# Restart - database will be recreated automatically
python main.py
```

### Plex OAuth Fails

**Error:** "Authentication failed" or popup won't close

**Solution:**
- Verify `PLEX_CLIENT_ID` is set in `.env`
- Check browser console for errors (F12)
- Try clearing browser cookies for localhost
- Ensure you're signed into Plex in your browser
- Check `PLEX_URL` and `PLEX_TOKEN` are correct

### Prowlarr Connection Failed

**Error:** "Failed to connect to Prowlarr"

**Solution:**
- Verify Prowlarr is running at `PROWLARR_URL`
- Check `PROWLARR_API_KEY` is correct
- Test URL in browser: http://localhost:9696
- Check Prowlarr logs for errors
- Ensure at least one indexer is configured in Prowlarr

### qBittorrent Connection Failed

**Error:** "Failed to authenticate with qBittorrent"

**Solution:**
- Verify qBittorrent is running
- Check Web UI is enabled (Tools → Options → Web UI)
- Test URL in browser: http://localhost:8080
- Verify `QBITTORRENT_USERNAME` and `QBITTORRENT_PASSWORD`
- Check qBittorrent isn't requiring HTTPS or additional authentication

### No Torrents Found

**Possible Causes:**
1. No indexers configured in Prowlarr
2. Indexers are down/unavailable
3. Search query doesn't match any results
4. TMDB ID not found in indexer databases

**Solution:**
- Check Prowlarr has indexers configured
- Test search directly in Prowlarr interface
- Try alternative media titles
- Check indexer status in Prowlarr

### Download Stalls or Fails

**Possible Causes:**
1. No seeders available
2. Network/firewall blocking torrent traffic
3. qBittorrent reached connection limit
4. Disk space full

**Solution:**
- Check torrent details in qBittorrent
- Verify port forwarding for qBittorrent
- Increase connection limits in qBittorrent settings
- Free up disk space
- Admin can manually retry failed requests

### Port Already in Use

**Error:** `Address already in use` on port 8000

**Solution:**
```powershell
# Windows: Find process using port 8000
netstat -ano | findstr :8000

# Kill the process (replace PID)
taskkill /F /PID <PID>
```

```bash
# Linux/Mac: Find and kill process
lsof -ti:8000 | xargs kill -9
```

### Permission Errors

**Error:** Permission denied when accessing directories

**Solution:**
- Ensure directories exist and are writable
- Check file permissions on Linux/Mac:
  ```bash
  chmod 755 /downloads /plex/movies /plex/tv
  ```
- On Windows, verify your user has write access to the directories

---

## Security Notes

### Critical Security Information

⚠️ **Never commit `.env` to Git** - contains all secrets  
⚠️ **First user becomes admin automatically** - ensure you login first  
⚠️ **Plex tokens are encrypted** using Fernet encryption  
⚠️ **JWT tokens expire** after 7 days (configurable)  
⚠️ **Use HTTPS in production** with a reverse proxy  

### .gitignore Protection

The following files/directories are automatically ignored:
- `.env` - Contains all secrets
- `data/plex_manager.db` - SQLite database
- `cache/` - TMDB image cache
- `__pycache__/` - Python bytecode
- `*.pyc` - Python compiled files

### Production Deployment

For production use:
1. Set `ENV=production` in `.env`
2. Use strong, unique passwords
3. Set up HTTPS with reverse proxy (Nginx/Apache)
4. Consider firewall rules to restrict access
5. Regular database backups
6. Monitor logs for security events

---

## Database Management

### Current: Auto-Initialization

The database automatically creates all tables on first startup using SQLAlchemy's `create_all()` method.

- Database file: `data/plex_manager.db`
- Tables created automatically
- No manual migration needed

### Fresh Install

To reset the database:
```bash
# Stop the application
# Delete the database file
Remove-Item data\plex_manager.db  # Windows
# rm data/plex_manager.db         # Linux/Mac

# Restart - tables recreated automatically
python main.py
```

**Note:** This deletes all data including users, requests, and downloads.

---

## Advanced Configuration

### Development vs Production

**Development Mode** (ENV=development):
- Detailed error messages
- Auto-reload on code changes
- Verbose logging
- CORS allows all origins

**Production Mode** (ENV=production):
- Generic error messages
- No auto-reload
- Production logging
- Strict CORS policy

### Customizing Port

Default port is 8000. To change:

Edit `main.py`:
```python
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)  # Change port here
```

Or use uvicorn directly:
```bash
uvicorn src.main_api:app --host 0.0.0.0 --port 8080
```

### Background Monitor Interval

The download monitor runs every 60 seconds by default.

To customize, edit scheduling in `src/main_api.py` or `main.py`.

---

## Getting Help

### Resources

- **Project Documentation**: See `PLANS.md` and `ROADMAP.md`
- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **PlexAPI Docs**: https://python-plexapi.readthedocs.io/
- **SQLAlchemy Docs**: https://docs.sqlalchemy.org/

### Common Issues

Most issues fall into these categories:
1. **Environment Variables** - Missing or incorrect `.env` values
2. **External Services** - Prowlarr/qBittorrent not running or misconfigured
3. **Network/Firewall** - Ports blocked or services unreachable
4. **Permissions** - Directory access or file permissions issues

### Debug Mode

Enable detailed logging in `.env`:
```env
ENV=development
```

Check console output for detailed error messages and stack traces.

---

## Next Steps

1. ✅ Setup complete - Application is running
2. ✅ Login with Plex OAuth
3. ✅ Search for media and make your first request
4. ✅ Monitor downloads in the dashboard
5. 📖 Review `ROADMAP.md` for upcoming features
6. 🔧 Configure retention system (if desired)
7. 📱 Bookmark http://localhost:8000 for easy access

---

*For additional setup questions or issues, please create an issue on the project repository.*
