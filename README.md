# Label Local

Label Local is a local web interface for a DYMO LabelWriter 4XL. It accepts shipping documents, finds the label using OCR and document geometry, and prepares a 4 × 6 print at 300 DPI.

The web interface supports manual crop adjustment before printing. The iPhone API skips the editor and prints automatically.

## Current home installation

Open [http://10.0.0.21:8080](http://10.0.0.21:8080) while connected to the home network.

The service is not authenticated and uses plain HTTP. Keep it on the trusted LAN. Do not expose port 8080 through the router or an internet-facing reverse proxy.

## Web interface

1. Open Label Local in a browser.
2. Upload a PDF, image, text, Markdown, or DOCX file.
3. Check the detected crop and adjust it if needed.
4. Change rotation or contrast if needed.
5. Select **Print label**.

Uploads are limited to 25 MB and documents to 30 pages. Working files stay on the Label Local host.

## iPhone Share Sheet shortcut

The shortcut endpoint is:

```text
http://10.0.0.21:8080/api/share
```

Every successful request to this endpoint prints one label immediately. It uses the first page, detects the label, crops it, scales it to the full 4 × 6 print area, and sends it to the default DYMO queue.

Create a new iOS Shortcut:

1. Open the Shortcut details and enable **Show in Share Sheet**.
2. Configure it to accept files.
3. Add **Get Contents of URL**.
4. Set the URL to `http://10.0.0.21:8080/api/share`.
5. Set the method to **POST**.
6. Set the request body to **Form**.
7. Add a field named `file`, choose the **File** type, and set its value to **Shortcut Input**.
8. Add **Get Dictionary Value** and retrieve `status` from the response.
9. Add an **If** action that shows `Label sent to printer` only when `status` is `queued`.
10. In the **Otherwise** branch, show the response so a failed upload is visible instead of reporting success.

The Shortcut works only while the iPhone can reach Label Local on the home network.

## API

Multipart upload:

```sh
curl -F file=@label.pdf http://10.0.0.21:8080/api/share
```

This command prints immediately.

The endpoint also accepts the file as a raw request body. Supply its original name using a query parameter or header:

```sh
curl --data-binary @label.pdf \
  'http://10.0.0.21:8080/api/share?filename=label.pdf'
```

A successful response includes `status: queued`, the CUPS message, and the detected crop coordinates. A printer failure returns HTTP 503.

## Run with Docker

Requirements:

- Docker with Compose support
- A working CUPS queue on the Docker host
- The DYMO queue named `DYMO_LabelWriter_4XL`
- The host CUPS socket at `/run/cups/cups.sock`

Start the application:

```sh
docker compose up --build -d
```

Then open `http://HOST-IP:8080`.

Override the queue or media name in `.env` when needed:

```env
PRINTER_NAME=DYMO_LabelWriter_4XL
PRINTER_MEDIA=1744907_4_in_x_6_in
```

## Development

```sh
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/uvicorn app.main:app --reload --port 8080
.venv/bin/pytest
```

The development server can process and preview documents without a printer. Actual printing requires access to a configured CUPS queue.

## Proxmox deployment

The current deployment is Proxmox LXC 116 at `10.0.0.21`:

- Debian 13
- Privileged LXC
- Docker nesting enabled
- Raw DYMO USB device passed into the LXC
- CUPS running inside the LXC
- Label Local running as a Docker container
- CUPS shared with the application through `/run/cups/cups.sock`
- LXC and application container configured to start automatically

The current USB passthrough path is `/dev/bus/usb/005/002`. Linux may assign a different device number after the printer is unplugged. The optional files under `deploy/proxmox` can update container 116 when that happens, but this host-level automation is not installed by default and should be reviewed before use.
