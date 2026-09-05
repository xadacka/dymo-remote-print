# Label Local

Label Local is a self-hosted web app for printing shipping labels (and, in a
pinch, ordinary photos) to a DYMO LabelWriter 4XL. Point it at a document —
from a browser, a script, or an iPhone Share Sheet — and it finds the label
on the page using OCR and document geometry, crops it, and prints a clean
4 × 6 label at 300 DPI. If it can't find a label at all (a normal photo, say),
it fills the whole page instead of guessing.

It runs anywhere Docker does, as long as it can reach a CUPS print queue for
your printer.

## Features

- Upload a PDF, image, text file, Markdown, or DOCX and get a ready-to-print
  4 × 6 label.
- Automatic label detection using document geometry and OCR, with a manual
  crop editor when it needs a nudge.
- Photos and documents with no detectable label print full-bleed instead of
  a bad guess.
- An `/api/share` endpoint built for the iOS Share Sheet: send a file to it
  and it prints immediately, no app required.
- Runs as a single Docker container in front of any CUPS print queue.

## Requirements

- Docker (with Compose support).
- A printer added to a CUPS queue that Label Local's container can reach.
  This project is built around a DYMO LabelWriter 4XL, but anything CUPS can
  print to will work — adjust `PRINTER_MEDIA` for your paper size.

If your printer isn't in CUPS yet, plug it in and check whether it's already
there:

```sh
lpstat -p
```

If not, CUPS's own web interface at `http://<cups-host>:631` can usually add
it in a couple of clicks, or on Debian/Ubuntu:

```sh
sudo apt install cups printer-driver-dymo   # driver package varies by printer
lpadmin -p DYMO_LabelWriter_4XL -E -v usb://DYMO/LabelWriter%204XL -m everywhere
```

## Quick start

Clone the repository, then choose one of the two setups below depending on
where CUPS is running.

### CUPS and Docker on the same Linux host

This is the simplest setup, and how the reference deployment below works:
share the CUPS socket directly with the container.

```yaml
# compose.yaml
services:
  label-local:
    build: .
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      PRINTER_NAME: DYMO_LabelWriter_4XL
      PRINTER_MEDIA: 1744907_4_in_x_6_in
    volumes:
      - label-data:/data
      - /run/cups:/run/cups   # the directory, not just cups.sock — see note below
volumes:
  label-data:
```

```sh
docker compose up --build -d
```

> Mount the `/run/cups` **directory**, not the `cups.sock` file by itself.
> `cupsd` deletes and recreates that socket file on every restart, which
> orphans a file-level bind mount and silently breaks printing until the
> container is recreated.

### CUPS running elsewhere (Docker Desktop, a NAS, any other OS)

Docker Desktop on macOS or Windows runs containers inside a VM that can't see
a host Unix socket, so this is also the setup to use there. CUPS supports
network printing out of the box — point `CUPS_SERVER` at any CUPS host on
your network instead of mounting a socket:

```yaml
services:
  label-local:
    build: .
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      CUPS_SERVER: cups-host.local:631
      PRINTER_NAME: DYMO_LabelWriter_4XL
      PRINTER_MEDIA: 1744907_4_in_x_6_in
    volumes:
      - label-data:/data
volumes:
  label-data:
```

The target CUPS server needs to allow remote access to the queue (`cupsctl
--remote-any`, or enable printer sharing in its settings) and be reachable
from wherever Docker is running.

Either way, once it's up, open `http://<host-ip>:8080` in a browser.

## Recommended setup: a dedicated Proxmox LXC

If you run Proxmox, this is the setup this project was actually built for and
the one that's been hardened the most: a small, dedicated, privileged LXC
with the printer's USB device passed straight through, running CUPS and the
Label Local container together. It survives reboots, container restarts, and
the printer being unplugged and replugged, without any manual fixing.

1. Create a privileged Debian 13 LXC with Docker nesting enabled, and note
   its container ID (the examples below assume `116` — use your own).
2. Plug the DYMO into the Proxmox host and pass it into the container. Find
   its bus/device path with `lsusb`, then set:

   ```sh
   pct set 116 --dev0 "path=/dev/bus/usb/BUS/DEVICE,gid=7,mode=0660"
   ```
3. Inside the container, install CUPS and the printer driver, add the queue,
   then build and run Label Local as in the same-host setup above.
4. Set the container and the Docker container to start automatically
   (`pct set 116 --onboot 1`, and `restart: unless-stopped` in Compose).

### Surviving a USB replug

A plain `dev0` passthrough is pinned to whatever bus/device numbers the
printer happened to enumerate at — those can change after a replug or a
host reboot, silently breaking the passthrough. The files under
`deploy/proxmox` fix that:

- `99-dymo-4xl.rules` — a udev rule that gives the printer a stable
  `/dev/dymo-4xl` symlink (matched by USB vendor/product ID, so it survives
  bus renumbering) and fires a systemd unit on every USB add event.
- `label-local-dymo-attach` / `label-local-dymo-attach.service` — that unit.
  It resolves the printer's current device path and, if it no longer matches
  the container's `dev0` config, stops the container, updates `dev0`, and
  starts it again.

To install them:

```sh
sudo install -m 0644 deploy/proxmox/99-dymo-4xl.rules /etc/udev/rules.d/
sudo install -m 0755 deploy/proxmox/label-local-dymo-attach /usr/local/sbin/
sudo install -m 0644 deploy/proxmox/label-local-dymo-attach.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo udevadm control --reload-rules
```

Edit the `container_id` at the top of `label-local-dymo-attach` first if your
container isn't `116`. Once installed, a physical unplug/replug (or the host
losing power and re-enumerating USB in a different order) self-heals with no
manual intervention.

## Using it

1. Open Label Local in a browser.
2. Upload a PDF, image, text, Markdown, or DOCX file.
3. Check the detected crop and adjust it if needed.
4. Change rotation or contrast if needed.
5. Select **Print label**.

Uploads are limited to 25 MB and documents to 30 pages. Working files stay on
the Label Local host.

## iPhone Share Sheet shortcut

The shortcut endpoint is:

```text
http://<host-ip>:8080/api/share
```

Every successful request to this endpoint prints one label immediately. It
uses the first page, detects the label, crops it, scales it to the full 4 × 6
print area, and sends it to the default printer queue.

Create a new iOS Shortcut:

1. Open the Shortcut details and enable **Show in Share Sheet**.
2. Configure it to accept files.
3. Add **Get Contents of URL**.
4. Set the URL to `http://<host-ip>:8080/api/share`.
5. Set the method to **POST**.
6. Set the request body to **File**.
7. Set that file value to **Shortcut Input**.
8. Add **Get Dictionary Value** and retrieve `status` from the response.
9. Add an **If** action that shows `Label sent to printer` only when `status`
   is `queued`.
10. In the **Otherwise** branch, show the response so a failed upload is
    visible instead of reporting success.

Do not use a Form request body for this Shortcut. It converts PDFs into
URL-encoded text and cannot print a valid label.

The Shortcut works only while your phone can reach Label Local on the same
network (or over a VPN like Tailscale if you've set that up).

## API

Multipart upload:

```sh
curl -F file=@label.pdf http://<host-ip>:8080/api/share
```

This command prints immediately.

The endpoint also accepts the file as a raw request body. Supply its original
name using a query parameter or header:

```sh
curl --data-binary @label.pdf \
  'http://<host-ip>:8080/api/share?filename=label.pdf'
```

A successful response includes `status: queued`, the CUPS message, and the
detected crop coordinates. A printer failure returns HTTP 503.

## Development

```sh
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/uvicorn app.main:app --reload --port 8080
.venv/bin/pytest
```

The development server can process and preview documents without a printer.
Actual printing requires access to a configured CUPS queue.

## License

[MIT](LICENSE)
