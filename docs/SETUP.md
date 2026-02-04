# Plex Manager Setup Guide

## Overview

Plex Manager is a unified media request and automation system that integrates with Plex, TMDB, Prowlarr, and qBittorrent to provide a Netflix-style interface for requesting and managing media.

## Quick Start (Recommended)

**New in 2026:** Plex Manager now includes an **automated setup wizard** that guides you through the entire configuration process!

### Prerequisites

- **Python 3.8+**
- **Plex Media Server** (for OAuth authentication and media library)
- **TMDB API Key** (free account at https://www.themoviedb.org/settings/api)
- **Prowlarr** (for torrent indexer aggregation)
- **qBittorrent** (with Web UI enabled)

### One-Command Setup

1. **Install Python Dependencies:**
   ```bash
   # Activate your virtual environment (if using one)
   # Windows PowerShell:
   .\.venv\Scripts\Activate.ps1
   
   # Linux/Mac:
   source .venv/bin/activate
   
   # Install dependencies
   pip install -r requirements.txt
   ```

2. **Run Plex Manager:**
   ```bash
   python main.py
   ```

3. **Follow the Setup Wizard:**
   - The wizard automatically launches on first run
   - It will auto-generate security keys (no manual commands needed!)
   - Prompts you for configuration with smart defaults
   - Tests each service connection before continuing
   - Validates all paths and creates necessary directories
   
4. **Done!** Your browser will open to http://localhost:8000

### What You'll Need

Before starting the wizard, have these ready:

1. **Plex Server Information:**
   - Server URL (usually `http://localhost:32400`)
   - Authentication token ([how to find it](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/))

2. **TMDB API Key:**
   - Get a free key at https://www.themoviedb.org/settings/api

3. **Prowlarr Details:**
   - URL (usually `http://localhost:9696`)
   - API key from Settings → General → Security

4. **qBittorrent Credentials:**
   - Web UI URL (usually `http://localhost:8080`)
   - Username and password

5. **Directory Paths** (must exist before setup):
   - Downloads folder (where qBittorrent saves files)
   - Movies library folder (where Plex reads movies)
   - TV shows library folder (where Plex reads TV shows)

> **Note:** The wizard will test connections and validate paths before saving your configuration!

---

## Re-running the Setup Wizard

If you need to reconfigure Plex Manager:

```bash
python main.py --setup
```

This will review your existing configuration and allow you to update any values.

---

## Service Installation (For Reference)

Before running the setup wizard, you'll need these services installed and running. See the [Manual Setup Guide](#manual-setup-guide) below for detailed installation instructions for:

- **Plex Media Server** - https://www.plex.tv/media-server-downloads/
- **Prowlarr** - https://prowlarr.com/#downloads  
- **qBittorrent** - https://www.qbittorrent.org/download.php
---

## First-Run Experience

### Launch the Application

```bash
python main.py
```

The application will:
- Check for `.env` configuration
- Launch setup wizard if needed (or if `--setup` flag is provided)
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

### First Login & Admin Setup

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

## Troubleshooting Setup Wizard

### Wizard Won't Start

**Problem:** Setup wizard doesn't launch automatically

**Solutions:**
- Ensure you've installed all dependencies: `pip install -r requirements.txt`
- Try forcing the wizard: `python main.py --setup`
- Check Python version: `python --version` (needs 3.8+)

### Plex Connection Failed

**Problem:** "Failed to connect to Plex server"

**Solutions:**
1. **Verify Plex is running:**
   - Open http://localhost:32400/web in your browser
   - Should see Plex Web App

2. **Check URL format:**
   - Must include `http://` prefix
   - Default port is 32400
   - Example: `http://localhost:32400` or `http://192.168.1.100:32400`

3. **Verify token:**
   - Follow instructions at https://support.plex.tv/articles/204059436/
   - Token is case-sensitive
   - Don't use `plex.tv/claim` token (different from server token!)

4. **Test manually:**
   ```bash
   # Windows PowerShell
   Invoke-WebRequest -Uri "http://localhost:32400/?X-Plex-Token=YOUR_TOKEN"
   
   # Linux/Mac
   curl "http://localhost:32400/?X-Plex-Token=YOUR_TOKEN"
   ```

### TMDB API Key Invalid

**Problem:** "Invalid TMDB API key"

**Solutions:**
1. **Get the correct key:**
   - Sign in to https://www.themoviedb.org/
   - Go to Settings → API
   - Use **API Key (v3 auth)** NOT the API Read Access Token

2. **Verify key format:**
   - Should be 32 alphanumeric characters
   - No spaces or special characters

3. **Test manually:**
   ```bash
   # Windows PowerShell
   Invoke-WebRequest -Uri "https://api.themoviedb.org/3/configuration?api_key=YOUR_KEY"
   ```

### Prowlarr Connection Failed

**Problem:** "Cannot connect to Prowlarr"

**Solutions:**
1. **Verify Prowlarr is running:**
   - Open http://localhost:9696 in browser
   - Should see Prowlarr UI

2. **Check API key:**
   - In Prowlarr: Settings → General → Security → API Key
   - Copy exactly (case-sensitive)

3. **Network issues:**
   - If using Docker, ensure port 9696 is exposed
   - Check firewall settings

### qBittorrent Authentication Failed

**Problem:** "Invalid qBittorrent username or password"

**Solutions:**
1. **Verify Web UI is enabled:**
   - qBittorrent → Tools → Options → Web UI
   - Enable "Web User Interface (Remote control)"

2. **Check credentials:**
   - Default username is usually `admin`
   - Password is what you set in Web UI settings

3. **Bypass authentication (local testing only):**
   - In qBittorrent Web UI settings
   - Check "Bypass authentication for clients on localhost"

4. **Test manually:**
   - Open http://localhost:8080 in browser
   - Try logging in with your credentials

### Path Validation Failed

**Problem:** "Path does not exist" or "Path is not writable"

**Solutions:**
1. **Create directories first:**
   - Downloads path: Must exist and be configured in qBittorrent
   - Movies/TV paths: Must exist and be configured in Plex

2. **Check permissions:**
   ```bash
   # Windows - ensure you have write access
   # Right-click folder → Properties → Security
   
   # Linux/Mac
   chmod 755 /path/to/directory
   ```

3. **Verify paths:**
   - Use absolute paths (e.g., `C:\Users\...\Downloads`, not relative)
   - Ensure drive letters are correct (Windows)
   - Ensure mount points exist (Linux/Docker)

4. **qBittorrent Downloads Path:**
   - Must match qBittorrent's "Save files to location"
   - Check: qBittorrent → Options → Downloads

5. **Plex Library Paths:**
   - Must match Plex library folder settings
   - Check: Plex → Settings → Libraries → Edit → Folders

### Rate Limit / Timeout Errors

**Problem:** "Connection timeout" or "Rate limit exceeded"

**Solutions:**
1. **Slow network:**
   - Increase timeout in wizard (requires code edit)
   - Check internet connection

2. **Service startup time:**
   - Wait for services to fully start before running wizard
   - Especially Prowlarr/Plex (can take 30-60 seconds)

3. **Retry:**
   - Wizard allows 3 attempts per field
   - Wait a few seconds between retries

### Wizard Crashed / Incomplete Setup

**Problem:** Wizard stopped mid-setup or .env is incomplete

**Solutions:**
1. **Restart wizard:**
   ```bash
   python main.py --setup
   ```
   - Wizard will detect existing values
   - You can review and update them

2. **Manual .env edit:**
   - See [Manual Setup Guide](#manual-setup-guide) below
   - Edit `.env` file directly

3. **Fresh start:**
   ```bash
   # Backup existing .env (optional)
   mv .env .env.backup
   
   # Run wizard fresh
   python main.py
   ```

---

## Manual Setup Guide

If you prefer manual configuration or the wizard doesn't work for your setup:

### Step 1: Generate Security Keys

```bash
# Generate SECRET_KEY
python -c "import secrets; print(f'SECRET_KEY={secrets.token_urlsafe(32)}')"

# Generate JWT_SECRET_KEY
python -c "import secrets; print(f'JWT_SECRET_KEY={secrets.token_urlsafe(32)}')"

# Generate PLEX_CLIENT_ID
python -c "import uuid; print(f'PLEX_CLIENT_ID={uuid.uuid4()}')"

# Generate ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(f'ENCRYPTION_KEY={Fernet.generate_key().decode()}')"
```

### Step 2: Create .env File

Copy `.env.example` to `.env`:
```bash
# Windows PowerShell
Copy-Item .env.example .env

# Linux/Mac
cp .env.example .env
```

### Step 3: Configure External Services

#### A. Plex Media Server

**Get Your Plex Server URL:**

Your Plex server URL is typically:
- **Local network**: `http://192.168.x.x:32400`
- **Localhost**: `http://localhost:32400`

To find it:
1. Open Plex Web App (app.plex.tv)
2. Go to Settings → Network
3. Note the server address and port (default: 32400)

**Get Your Plex Token:**

**Method 1: Through Plex Web App**
1. Sign in to app.plex.tv
2. Open any media item
3. Click "..." → "Get Info" → "View XML"
4. Find `X-Plex-Token=XXXXX` in the URL
5. Copy the token value

**Method 2: Official Documentation**
1. Go to https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/
2. Follow the instructions for your platform

**Update .env:**
```env
PLEX_URL=http://192.168.1.100:32400
PLEX_TOKEN=your-plex-token-here
```

---

#### B. TMDB API

1. Create a free account at https://www.themoviedb.org/signup
2. Go to https://www.themoviedb.org/settings/api
3. Request an API key (fill out the form with your app info)
4. Copy the **API Key (v3 auth)**

**Update .env:**
```env
TMDB_API_KEY=your-tmdb-api-key-here
```

---

#### C. Prowlarr Setup

Prowlarr aggregates multiple torrent indexers into a single API.

**Installation:**

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

**Configuration:**

1. Open Prowlarr at http://localhost:9696
2. **Add Indexers:**
   - Go to Indexers → Add Indexer
   - Add your preferred indexers (1337x, RARBG, The Pirate Bay, etc.)
   - Configure each indexer with required credentials/cookies
3. **Get API Key:**
   - Go to Settings → General → Security
   - Copy the API Key

**Update .env:**
```env
PROWLARR_URL=http://localhost:9696
PROWLARR_API_KEY=your-prowlarr-api-key-here
```

---

#### D. qBittorrent Setup

qBittorrent is the download client for torrents.

**Installation:**

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

**Enable Web UI:**

1. Open qBittorrent application
2. Go to Tools → Options → Web UI
3. **Enable the Web User Interface**
4. Set Port: `8080` (default)
5. Set Username: `admin` (or custom)
6. Set Password: (choose a strong password)
7. Click "Save"

**Test Web UI:**
- Open http://localhost:8080
- Login with your username/password
- You should see the qBittorrent Web UI

**Update .env:**
```env
QBITTORRENT_URL=http://localhost:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=your-password-here
```

---

### Step 4: Configure Directory Paths

Plex Manager needs paths for downloads and media libraries.

**Create Required Directories:**

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

**Update .env:**
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

### Step 5: Complete .env Configuration

Your final `.env` file should contain all these variables:

```env
# Security Keys (generated in Step 1)
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
- CORS allows localhost origins

**Production Mode** (ENV=production):
- Generic error messages
- No auto-reload
- Production logging
- Strict CORS policy
- Secure cookies (requires HTTPS)

**Note:** Setup wizard sets `ENV=development` by default for easier local testing.

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
1. **Environment Variables** - Missing or incorrect `.env` values (use wizard to fix!)
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
