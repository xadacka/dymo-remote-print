# Label Local

Label Local turns shipping paperwork into 4 × 6 labels. It runs entirely on a home network, accepts PDFs, images, text, Markdown and DOCX files, suggests the label region using geometry and OCR, lets the user adjust the crop, and prints through CUPS to a DYMO LabelWriter 4XL.

## Run with Docker

```sh
docker compose up --build -d
```

Open `http://HOST-IP:8080`. The interface is deliberately served over plain HTTP for a trusted local network and has no internet-facing authentication. Do not expose port 8080 through a router or public reverse proxy.

The container sends jobs to CUPS on the Docker host. The host must have the DYMO installed and must allow local-network CUPS clients. Override the queue name in a `.env` file if necessary:

```env
PRINTER_NAME=DYMO_LabelWriter_4XL
```

## Development

```sh
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/uvicorn app.main:app --reload --port 8080
.venv/bin/pytest
```

Uploaded documents are transient working files under `DATA_DIR`. No document leaves the host.

## iPhone share sheet shortcut

Label Local exposes `POST /api/share` for iOS Shortcuts. The response contains an `open_url` that opens the uploaded file directly in the crop editor. Shared documents expire after 24 hours.

Create a Shortcut that accepts files from the Share Sheet, then add these actions:

1. **Get Contents of URL**: `http://LABEL-LOCAL-IP:8080/api/share`
2. Set method to **POST**, request body to **Form**, add the key `file`, set its type to **File**, and use **Shortcut Input** as its value.
3. **Get Dictionary Value**: retrieve `open_url` from the previous action.
4. **Open URLs**: open that value.

The endpoint also accepts a raw request body when the original filename is supplied as `?filename=label.pdf` or in the `X-Filename` header.

Example multipart request:

```sh
curl -F file=@label.pdf http://LABEL-LOCAL-IP:8080/api/share
```

Example response:

```json
{
  "document_id": "...",
  "filename": "label.pdf",
  "pages": 1,
  "open_url": "http://LABEL-LOCAL-IP:8080/?document=...&name=label.pdf"
}
```

The Shortcut only works while the phone can reach Label Local on the home network.

## Proxmox deployment

The home deployment uses a dedicated Debian LXC with Docker nesting enabled. CUPS runs inside the LXC and owns the USB-connected DYMO; the application remains in its Docker container and submits jobs to CUPS over the container bridge.

The LXC is privileged because raw USB printer passthrough and nested Docker need host-level device access. Keep the service on the trusted LAN, do not configure router port forwarding, and do not publish it through an internet-facing reverse proxy.
