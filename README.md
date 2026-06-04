# Festival Finder

Festival Finder is a small web app for festival crowd coordination:

- upload a band timetable with band, festival, stage, date, and time
- open a band page for that set
- let friends check in with a display name
- store their GPS coordinates
- upload a POV photo and a side photo so other people can see where they are watching

The current implementation uses simple name-based check-ins for each band page. It does not include account passwords or private friend groups yet.

## Tech stack

- Python 3.12.9
- Flask
- SQLite
- Gunicorn
- Docker
- local file uploads for timetable files and crowd photos
- OpenStreetMap and Apple Maps links for attendee locations

## Run locally

Use Python 3.12.9 locally. The pinned version lives in [`.python-version`](.python-version) so GitHub Actions and Railway build the same runtime.

1. Create a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Start the app:

   ```bash
   python app.py
   ```

4. Open `http://127.0.0.1:5001`

Uploads and the SQLite database are stored under `data/` by default.

### Local HTTPS for iPhone testing

You can run the local server over HTTPS:

1. Generate a development certificate:

   ```bash
   ./scripts/generate_dev_cert.sh
   ```

   The script includes `localhost`, your Mac hostname, and your current LAN IP in the certificate when it can detect them.
   If your LAN IP is not detected automatically, pass it explicitly:

   ```bash
   ./scripts/generate_dev_cert.sh 192.168.1.12
   ```

2. Start the app with local HTTPS enabled:

   ```bash
   LOCAL_HTTPS=1 python app.py
   ```

3. Open one of these URLs:

   - `https://localhost:5001` on your Mac
   - `https://Michels-MacBook-Pro.local:5001` on devices on the same network

Important: the generated certificate is self-signed. For browser geolocation on iPhone, Safari must trust the certificate. If Safari still treats the page as insecure, use a Railway URL or another HTTPS tunnel with a publicly trusted certificate.

### Map links

No external map API key is required.

Band pages link attendee coordinates to OpenStreetMap. The `Navigate` button uses Apple Maps for walking directions, and on iPhone it tries the native Maps app first before falling back to the web URL.

Important for iPhone testing: Safari only allows browser geolocation on secure origins. That means:

- `https://your-app.up.railway.app` should work
- `http://192.168.x.x:5001` from your phone will be blocked
- `LOCAL_HTTPS=1 python app.py` can work for local HTTPS, but the certificate must be trusted on the phone
- Railway, Render, or an HTTPS tunnel is still the cleanest option for phone testing

## Deploy with GitHub + Railway

GitHub should hold the source code. Railway should run the server.

1. Create a new GitHub repository and push this project to it:

   ```bash
   git add .
   git commit -m "Prepare Festival Finder for deployment"
   git branch -M main
   git remote add origin git@github.com:YOUR_USER/festival-finder.git
   git push -u origin main
   ```

2. GitHub Actions will run the checked-in [CI workflow](.github/workflows/ci.yml) on pushes and pull requests.
3. In Railway, choose **New Project** -> **Deploy from GitHub repo**.
4. Select this repository.
5. Railway will detect the checked-in [`railway.json`](railway.json), build the included [`Dockerfile`](Dockerfile), start Gunicorn, and health-check `/health`.
6. In the service **Variables** tab, set these before redeploying:

   ```bash
   SECRET_KEY=replace-with-a-generated-secret
   ```

   You can generate a `SECRET_KEY` locally with:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

7. Attach a Railway volume to the service and mount it at `/data`.
8. Generate a public domain in the service **Settings** -> **Networking** section.

If an earlier Railway service has a custom **Build Command** set to `pip install -r requirements.txt`, clear it or redeploy after pushing this repo. The checked-in Railway config sets `buildCommand` to `null` so the Dockerfile controls dependency installation with `python -m pip`.

Railway automatically exposes the `RAILWAY_VOLUME_MOUNT_PATH` environment variable for attached volumes. This app now uses that mount path automatically for the SQLite database and uploads when `DATABASE_PATH` and `UPLOAD_ROOT` are not set explicitly.

### Railway troubleshooting

If Railway shows `Worker failed to boot` and `/health` never receives a response, check the service **Variables** tab first. The app has a built-in security check that blocks startup on Railway when `SECRET_KEY` is missing, still set to a placeholder, or still using the development default.

Set `SECRET_KEY` to a real value in Railway, then redeploy.

### Important Railway note

This app stores uploads and SQLite data on disk. Railway deployments are ephemeral unless you attach a persistent volume.

Without a volume, uploaded timetable files, POV photos, side photos, and the SQLite database will disappear after redeploys or restarts.

The included [`.env.example`](.env.example) file documents the variables you can paste into Railway's raw variable editor.

If you prefer explicit paths instead of Railway's automatic volume detection, set:

```bash
DATABASE_PATH=/data/festival_finder.db
UPLOAD_ROOT=/data/uploads
```

### Render

The existing [`render.yaml`](render.yaml) is still usable if you decide to deploy on Render instead. It creates a persistent disk and generates `SECRET_KEY`.

If Render shows `Worker failed to boot`, check the earlier log lines for the exact Python exception. A common cause is a missing production variable from an older Render service; make sure `SECRET_KEY` is set in Render's environment.

### Admin page

The public crowd check-in flow stays open. Timetable management and delete actions are available from `/admin`.

Important: the admin page is not password protected. Only share the public URL with people you trust to manage the timetable.

## Tests

Run the test suite with:

```bash
python -m unittest discover -s tests
```
