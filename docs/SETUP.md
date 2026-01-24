# Plex Manager Setup Guide

## Initial Configuration

Before using Plex Manager, you need to configure your Plex server credentials.

### Step 1: Locate Your Config File

The configuration file should be located at:
```
data/plex.config
```

If this file doesn't exist, run the application once and it will automatically create a template for you.

### Step 2: Get Your Plex Server URL

Your Plex server URL is typically in one of these formats:
- **Local network**: `http://192.168.x.x:32400`
- **Localhost**: `http://localhost:32400`
- **Remote (Plex.tv)**: `https://your-server-address.plex.direct:32400`

To find your server URL:
1. Open Plex Web App in your browser
2. Go to Settings → Network
3. Note the server address and port (default is 32400)

### Step 3: Get Your Plex Token

Your Plex authentication token is required to access the API.

**Method 1: Through Plex Web App (Easiest)**
1. Sign in to Plex Web App (app.plex.tv)
2. Open any media item
3. Click the "..." menu and select "Get Info"
4. Click "View XML"
5. Look in the URL bar for `X-Plex-Token=XXXXX`
6. Copy the token value after the equals sign

**Method 2: Through Server Settings**
1. Open Plex Web App
2. Go to Settings → Your Account
3. At the bottom, you'll see "Authorization"
4. Your token will be displayed there

### Step 4: Update Your Config File

Open `data/plex.config` in a text editor and replace the placeholder values:

```json
{
  "plex_url": "http://192.168.1.100:32400",
  "plex_token": "your-actual-plex-token-here"
}
```

**Example:**
```json
{
  "plex_url": "http://192.168.0.173:32400",
  "plex_token": "AbCdEfGhIjKlMnOpQrSt"
}
```

### Step 5: Verify Configuration

Run the application again. If configured correctly, it should connect to your Plex server without errors.

## Security Notes

- ⚠️ **Never commit your `plex.config` file to Git** - it contains sensitive credentials
- The `.gitignore` file is already configured to exclude this file
- Keep your Plex token private - it provides full access to your Plex server
- Consider using a dedicated Plex account with limited permissions if sharing code

## Troubleshooting

### "Connection refused" or "Unable to connect"
- Verify your Plex server is running
- Check that the URL and port are correct
- Ensure firewall isn't blocking the connection
- Try using `localhost` instead of IP address if running locally

### "Unauthorized" or authentication errors
- Double-check your Plex token is correct
- Ensure there are no extra spaces in the config file
- Try generating a new token from Plex

### "Config file not found"
- Make sure you're running the script from the correct directory
- Verify the `data/` folder exists
- Check file permissions

For additional help, refer to the [PlexAPI documentation](https://python-plexapi.readthedocs.io/).
