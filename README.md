# abogen <img width="40px" title="abogen icon" src="https://raw.githubusercontent.com/denizsafak/abogen/refs/heads/main/abogen/assets/icon.ico" align="right" style="padding-left: 10px; padding-top:5px;">

Abogen is a web-first text-to-speech workstation. Drop in an EPUB, PDF, Markdown, or plain text file and Abogen will turn it into high-quality audio with perfectly synced subtitles. The new interface runs entirely inside your browser using Flask + htmx, so it behaves like a modern web app whether you launch it locally or from a container.

## Highlights
- Natural-sounding speech powered by Kokoro-82M with per-job voice, speed, GPU toggle, and subtitle style controls
- Clean dashboard that tracks the status, progress, and logs of every job in real time (thanks to htmx partial updates)
- Automatic chapter detection and subtitle generation with SRT/ASS exports
- LLM-assisted text normalization with live previews and configurable prompts
- Runs well in Docker, ships a REST-style JSON API, and works across macOS, Linux, and Windows

## Interfaces

Abogen offers **two interfaces** to suit different workflows:

| Command | Interface | Best for |
|---------|-----------|----------|
| `abogen` | PyQt6 Desktop GUI | Local desktop use on Windows/macOS/Linux |
| `abogen-web` | Flask Web UI | Docker, headless servers, remote access |

Both interfaces share the same core processing engine and produce identical output.

## Quick start
Abogen supports Python 3.10–3.12.

### Install with pip
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
pip install -e .[dev]      # We need to use this until pushing this branch to main
```

### Launch the desktop app (PyQt6)
```bash
abogen
```

### Launch the web app (Flask)
```bash
abogen-web
```

Then open http://localhost:8808 and drag in your documents. Jobs run in the background worker and the browser updates automatically.

> **Tip:** Keep the terminal open while the server is running. Use `Ctrl+C` to stop it.

## Container image
A lightweight Dockerfile lives in `abogen/Dockerfile`.

```bash
docker build -t abogen .
mkdir -p ~/abogen-data/uploads ~/abogen-data/outputs
docker run --rm \
  -p 8808:8808 \
  -v ~/abogen-data:/data \
  --name abogen \
  abogen
```

Browse to http://localhost:8808. Uploaded source files are stored in `/data/uploads` and rendered audio/subtitles appear in `/data/outputs`.

### Container environment variables
| Variable | Default | Purpose |
|----------|---------|---------|
| `ABOGEN_HOST` | `0.0.0.0` | Bind address for the Flask server |
| `ABOGEN_PORT` | `8808` | HTTP port |
| `ABOGEN_DEBUG` | `false` | Enable Flask debug mode |
| `ABOGEN_UPLOAD_ROOT` | `/data/uploads` | Directory where uploaded files are stored |
| `ABOGEN_OUTPUT_ROOT` | `/data/outputs` | Directory for generated audio and subtitles (legacy alias of `ABOGEN_OUTPUT_DIR`) |
| `ABOGEN_OUTPUT_DIR` | `/data/outputs` | Container path for rendered audio/subtitles |
| `ABOGEN_SETTINGS_DIR` | `/config` | Container path for JSON settings/configuration |
| `ABOGEN_TEMP_DIR` | `/data/cache` (Docker) or platform cache dir | Container path for temporary audio working files |
| `ABOGEN_UID` | `1000` | UID that the container should run as (matches host user) |
| `ABOGEN_GID` | `1000` | GID that the container should run as (matches host group) |
| `ABOGEN_LLM_BASE_URL` | `""` | OpenAI-compatible endpoint used to seed the Settings → LLM panel |
| `ABOGEN_LLM_API_KEY` | `""` | API key passed to the endpoint above |
| `ABOGEN_LLM_MODEL` | `""` | Default model selected when you refresh the model list |
| `ABOGEN_LLM_TIMEOUT` | `30` | Timeout (seconds) for server-side LLM requests |
| `ABOGEN_LLM_CONTEXT_MODE` | `sentence` | Default prompt context window (`sentence`, `paragraph`, `document`) |
| `ABOGEN_LLM_PROMPT` | `""` | Custom normalization prompt template seeded into the UI |

Set any of these with `-e VAR=value` when starting the container.

To discover your local UID/GID for matching file permissions inside the container, run:

```bash
id -u
id -g
```

Use those values to populate `ABOGEN_UID` / `ABOGEN_GID` in your `.env` file.

When running via Docker Compose, set `ABOGEN_SETTINGS_DIR`,
`ABOGEN_OUTPUT_DIR`, and `ABOGEN_TEMP_DIR` in your `.env` file to the host
directories you want mounted into the container. Compose maps them to
`/config`, `/data/outputs`, and `/data/cache` respectively while exporting
those in-container paths to the application. Non-audio caches (e.g., Hugging
Face downloads) stick to the container's internal cache under `/tmp/abogen-home/.cache`
by default, so only conversion scratch data touches the mounted `ABOGEN_TEMP_DIR`.
Ensure each host directory exists and is writable by the UID/GID you configure
before starting the stack.

### Docker Compose (GPU by default)
The repo includes `docker-compose.yaml`, which targets GPU hosts out of the box. Install the NVIDIA Container Toolkit and run:

```bash
docker compose up -d --build
```

Key build/runtime knobs:

- `TORCH_VERSION` – pin a specific PyTorch release that matches your driver (leave blank for the latest on the configured index).
- `TORCH_INDEX_URL` – swap out the PyTorch download index when targeting a different CUDA build.
- `ABOGEN_DATA` – host path that stores uploads/outputs (defaults to `./data`).

CPU-only deployment: comment out the `deploy.resources.reservations.devices` block (and the optional `runtime: nvidia` line) inside the compose file. Compose will then run without requesting a GPU. If you prefer the classic CLI:

```bash
docker build -f abogen/Dockerfile -t abogen-gpu .
docker run --rm \
  --gpus all \
  -p 8808:8808 \
  -v ~/abogen-data:/data \
  abogen-gpu
```

## GPU acceleration
Abogen detects CUDA automatically. To use an NVIDIA GPU, install the matching PyTorch build before installing Abogen:
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install abogen
```

On Linux with AMD GPUs, install PyTorch/ROCm nightly wheels:
```bash
pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/rocm6.4
```
Abogen falls back to CPU rendering if no GPU is available.

## Using the web UI
1. Upload a document (drag & drop or use the upload button).
2. Choose voice, language, speed, subtitle style, and output format.
3. Click **Create job**. The job immediately appears in the queue.
4. Watch progress and logs update live. Download audio/subtitle assets when complete.
5. Cancel or delete jobs any time. Download logs for troubleshooting.

Multiple jobs can run sequentially; the worker processes them in order.

## LLM-assisted text normalization
Abogen can hand tricky apostrophes and contractions to an OpenAI-compatible large language model. Configure it from **Settings → LLM**:

1. Enter the base URL for your endpoint (Ollama, OpenAI proxy, etc.) and an API key if required. Use the server root (for Ollama: `http://localhost:11434`)—Abogen appends `/v1/...` automatically, but it also accepts inputs that already end in `/v1`.
2. Click **Refresh models** to load the catalog, pick a default model, and adjust the timeout or prompt template.
3. Use the preview box to test the prompt, then save the settings. The Normalization panel can synthesize a short audio preview with the current configuration.

When you are running inside Docker or a CI pipeline, seed the form automatically with `ABOGEN_LLM_*` variables in your `.env` file. The `.env.example` file includes sample values for a local Ollama server.

## JSON endpoints
Need machine-readable status updates? The dashboard calls a small set of helper endpoints you can reuse:
- `GET /api/jobs/<id>` returns job metadata, progress, and log lines in JSON.
- `GET /partials/jobs` renders the live job list as HTML (htmx uses this for polling).
- `GET /partials/jobs/<id>/logs` renders just the log window.

More automation hooks are planned; contributions are very welcome if you need additional routes.

## Audiobookshelf integration
Abogen can push finished audiobooks directly into Audiobookshelf. Configure this under **Settings → Integrations → Audiobookshelf** by providing:

- **Base URL** – the HTTPS origin (and optional path prefix) where your Audiobookshelf server is reachable, for example `https://abs.example.com` or `https://media.example.com/abs`. Do **not** append `/api`.
- **Library ID** – the identifier of the target Audiobookshelf library (copy it from the library’s settings page in ABS).
- **Folder (name or ID)** – the destination folder inside that library. Enter the folder name exactly as it appears in Audiobookshelf (Abogen resolves it to the correct ID automatically), paste the raw `folderId`, or click **Browse folders** to fetch the available folders and populate the field.
- **API token** – a personal access token generated in Audiobookshelf under *Account → API tokens*.

You can enable automatic uploads for future jobs or trigger individual uploads from the queue once the connection succeeds.

### Reverse proxy checklist (Nginx Proxy Manager)
When Audiobookshelf sits behind Nginx Proxy Manager (NPM), make sure the API paths and headers reach the backend untouched:

1. Create a **Proxy Host** that points to your ABS container or host (default forward port `13378`).
2. Under the **SSL** tab, enable your certificate and tick **Force SSL** if you want HTTPS only.
3. In the **Advanced** tab, append the snippet below so bearer tokens, client IPs, and large uploads survive the proxy hop:
   ```nginx
  proxy_set_header Host $host;
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
  proxy_set_header X-Forwarded-Host $host;
  proxy_set_header X-Forwarded-Port $server_port;
  proxy_set_header Authorization $http_authorization;
  client_max_body_size 5g;
  proxy_read_timeout 300s;
  proxy_connect_timeout 300s;
   ```
4. Disable **Block Common Exploits** (it strips Authorization headers in some NPM builds).
5. Enable **Websockets Support** on the main proxy screen (Audiobookshelf uses it for the web UI, and it keeps the reverse proxy configuration consistent).
6. If you publish Audiobookshelf under a path prefix (for example `/abs`), add a **Custom Location** with `Location: /abs/` and set the **Forward Path** to `/`. That rewrite strips the `/abs` prefix before traffic reaches Audiobookshelf so `/abs/api/...` on the internet becomes `/api/...` on the backend. Use the same prefixed URL in Abogen’s “Base URL” field.

After saving the proxy host, test the API from the machine running Abogen:

```bash
curl -i "https://abs.example.com/api/libraries" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```

If you still receive `Cannot GET /api/...`, the proxy is rewriting paths. Double-check the **Custom Locations** table (the `Forward Path` column should be empty for `/abs/`) and review the NPM access/error logs while issuing the curl request to confirm the backend sees the full `/api/libraries` URL.

A JSON response confirming the libraries list means the proxy is routing API calls correctly. You can then use **Browse folders** to confirm the library contents, run **Test connection** in Abogen’s settings (it verifies the library and resolves the folder), and use the “Send to Audiobookshelf” button on completed jobs.

## Configuration reference
Most behaviour is controlled through the UI, but a few environment variables are helpful for automation:
- `ABOGEN_SECRET_KEY` – provide your own random secret when deploying across multiple replicas.
- `ABOGEN_DEBUG` – set to `true` for verbose Flask error output.
- `ABOGEN_SETTINGS_DIR` – change where Abogen stores its JSON settings/configuration files.
- `ABOGEN_TEMP_DIR` – change where temporary uploads and cache files are stored.
- `ABOGEN_OUTPUT_DIR` – change where rendered audio/subtitles are written.
- `ABOGEN_LLM_*` – seed the Settings → LLM panel with defaults for base URL, API key, model, timeout, prompt, and context mode.

If unset, Abogen picks sensible defaults suitable for local usage.

You can also create a `.env` file in the project root (see `.env.example`) to configure these paths when running locally. The application loads `.env` automatically on startup.

## Development workflow
```bash
git clone https://github.com/denizsafak/abogen.git
cd abogen
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
```

Run the server in development mode:
```bash
export ABOGEN_DEBUG=true
abogen
```

Static files live in `abogen/web/static`, templates in `abogen/web/templates`, and the conversion pipeline in `abogen/web/conversion_runner.py`.

## Tests
```bash
python -m pytest
```

Unit tests cover the queue service, web routes, and conversion pipeline helpers. Contributions that add features should include new tests whenever practical.

## Upgrading from the desktop GUI
The legacy PyQt5 interface is no longer packaged. Existing scripts that call `abogen.main` should switch to the new web entry point (`abogen.webui.app:main`). The new experience works headlessly, plays nicely in Docker, and exposes JSON APIs for automation.

## Troubleshooting
- Conversion jobs stay pending → ensure the background worker has write access to the upload/output directories.
- GPU not detected → verify the correct PyTorch wheel is installed (`pip show torch`) and drivers match the container/host.
- Subtitle files missing → check the job configuration; subtitles are optional and can be disabled per job.
- Logs are empty → run with `ABOGEN_DEBUG=true` to get verbose Flask error output in the server console.

If you hit a bug, open an issue describing the input file and the exact log output.

## Contributing
Pull requests are welcome! Please:
- Keep changes focused and well-tested
- Run `python -m pytest`
- Update documentation when behaviour changes

Thanks for helping make Abogen a great open-source audiobook generator.
