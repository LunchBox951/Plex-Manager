# Plex Manager Setup Guide

## Initial Setup

Plex Manager uses Plex OAuth for user authentication and environment variables for configuration.

### Step 1: Install Dependencies

Make sure you have Python 3.8+ and a virtual environment set up:

```bash
# Activate your virtual environment
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Generate Environment Variables

Plex Manager requires several environment variables for security. Run these commands to generate them:

```bash
# Generate SECRET_KEY (for JWT tokens)
python -c "import secrets; print(f'SECRET_KEY={secrets.token_urlsafe(32)}')"

# Generate PLEX_CLIENT_ID (for OAuth)
python -c "import uuid; print(f'PLEX_CLIENT_ID={uuid.uuid4()}')"

# Generate ENCRYPTION_KEY (for token encryption)
python -c "from cryptography.fernet import Fernet; print(f'ENCRYPTION_KEY={Fernet.generate_key().decode()}')"
```

### Step 3: Create .env File

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Open `.env` in a text editor and paste the generated values from Step 2:
   ```env
   SECRET_KEY=your-generated-secret-key
   PLEX_CLIENT_ID=your-generated-uuid
   DATABASE_URL=sqlite:///./data/plex_manager.db
   ENCRYPTION_KEY=your-generated-fernet-key
   ENV=development
   
   # Plex Configuration (optional for system-level operations)
   PLEX_URL=http://192.168.x.x:32400
   PLEX_TOKEN=your-plex-token
   
   # TMDB API Configuration (optional)
   TMDB_API_KEY=your-tmdb-api-key
   ```

### Step 4: Launch the Application

```bash
python main.py
```

The application will:
- Initialize the database
- Start the web server on http://localhost:8000
- Display startup logs

### Step 5: First Login

1. Open your browser to http://localhost:8000
2. Click "Sign in with Plex"
3. Complete the Plex OAuth authentication
4. **The first user becomes an administrator automatically**

## Authentication Flow

### Current: Development OAuth (Anonymous Client ID)

During development, Plex Manager uses an anonymous Client ID (UUID). This means:
- OAuth works immediately without approval
- Auth screen shows "Unknown Application"
- Suitable for personal use and testing

### Future: Production OAuth (Official Client ID)

Before public release, register your application with Plex:

1. Visit https://www.plex.tv/partners/
2. Submit app details (name, description, icon, redirect URIs)
3. Wait for Plex approval (1-2 weeks)
4. Replace `PLEX_CLIENT_ID` in `.env` with official ID
5. Users will see your branded app name in OAuth screen

## Plex Configuration

For system-level Plex operations (library scanning, etc.), configure Plex credentials in your `.env` file:

### Get Your Plex Server URL

Your Plex server URL is typically:
- **Local network**: `http://192.168.x.x:32400`
- **Localhost**: `http://localhost:32400`

To find it:
1. Open Plex Web App
2. Go to Settings → Network
3. Note the server address and port (default: 32400)

### Get a Plex Token

**Method 1: Through Plex Web App**
1. Sign in to app.plex.tv
2. Open any media item
3. Click "..." → "Get Info" → "View XML"
4. Find `X-Plex-Token=XXXXX` in the URL
5. Copy the token value

**Method 2: Through Server Settings**
1. Open Plex Web App
2. Go to Settings → Your Account
3. Look for "Authorization" section
4. Copy the displayed token

### Update .env File

Add these values to your `.env` file:

```env
PLEX_URL=http://192.168.1.100:32400
PLEX_TOKEN=your-plex-token-here
TMDB_API_KEY=your-tmdb-api-key
```

## Security Notes

- ⚠️ **Never commit `.env` to Git** - contains all secrets
- `.gitignore` is already configured to exclude sensitive files
- Plex tokens stored in database are encrypted with Fernet
- JWT tokens expire after 7 days
- Use `ENV=production` with HTTPS in production

## Database Management

### Current: Auto-initialization

The database automatically creates tables on startup using SQLAlchemy's `create_all()`.

**To reset the database:**
```bash
# Stop the application
# Delete the database file
rm data/plex_manager.db

# Restart - database will be recreated
python main.py
```

### Future: Alembic Migrations

Before production deployment, migrate to Alembic for proper schema management:

```bash
# Initialize Alembic
alembic init alembic

# Create initial migration
alembic revision --autogenerate -m "Initial schema"

# Apply migrations
alembic upgrade head
```

Remove the `Base.metadata.create_all()` call from `src/database.py` after migrating to Alembic.

## Troubleshooting

## Troubleshooting

### Missing Environment Variables Error

**Error:** `ERROR: Missing required environment variables`

**Solution:**
- Make sure `.env` file exists in the project root
- Verify all required variables are set (SECRET_KEY, PLEX_CLIENT_ID, ENCRYPTION_KEY)
- Run the key generation commands from Step 2

### Database Errors

**Error:** `Table already exists` or migration errors

**Solution:**
```bash
# Delete the database and restart
rm plex_manager.db
python main.py
```

### Plex OAuth Fails

**Error:** "Authentication failed" or popup won't close

**Solution:**
- Verify `PLEX_CLIENT_ID` is set in `.env`
- Check browser console for errors
- Try clearing browser cookies for localhost
- Ensure you're signed into Plex in your browser

### Port Already in Use

**Error:** `Address already in use`

**Solution:**
```bash
# Find process using port 8000
# Windows PowerShell:
netstat -ano | findstr :8000

# Kill the process (replace PID with actual process ID)
taskkill /F /PID <PID>
```

### Import Errors

**Error:** `ModuleNotFoundError`

**Solution:**
```bash
# Reinstall dependencies
pip install -r requirements.txt
```

For additional help:
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [PlexAPI Documentation](https://python-plexapi.readthedocs.io/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
