# PixelFlow — Image Processing Pipeline in Racket

A local image processing pipeline built in **Racket** that exposes a web interface for applying filters to images using three distinct programming paradigms: sequential mutation, pure functional recursion, and parallel execution with `futures`.

Developed as a course project for **Implementation of Computational Methods** — Tecnológico de Monterrey.

> **Authors:** Ivan Burrola · Alberto Lopez · Axel Lugo · Sebastian Viche

---

## Table of Contents

- [Project Description](#project-description)
- [Architecture](#architecture)
- [Implemented Filters](#implemented-filters)
- [Execution Paradigms](#execution-paradigms)
- [Requirements](#requirements)
- [Installation & Usage](#installation--usage)
- [File Structure](#file-structure)
- [API Reference](#api-reference)

---

## Project Description

PixelFlow lets you load an image, choose a filter, and choose how the processing is executed. The Racket backend applies the filter over the image's ARGB byte buffer, measures the real execution time, and returns the processed image encoded in Base64 to be rendered directly in the browser.

The academic goal is to **compare performance** across three paradigms applied to the same computational task, observing how the choice of computation model impacts processing time.

---

## Architecture

```
Browser (index.html)
        │
        │  POST /api/process  { image, filter, approach, workers? }
        ▼
htmlcontroller.rkt   ← HTTP server (web-server/servlet-env)
        │
        ▼
mainbase.rkt         ← Orchestrator: loads bitmap, measures time, serializes
        │
        ├── filtrossecuenciales.rkt   (in-place byte mutation)
        ├── filtrosrecursivos.rkt     (immutable lists + recursion)
        └── filtrosparalelos.rkt      (Racket futures, N workers)
```

The server responds with:

```json
{
  "base64Image": "<png encoded in base64>",
  "timeMs": 42
}
```

---

## Implemented Filters

| Filter | Description | Kernel / Formula |
|---|---|---|
| **Negative** | Inverts each color channel | `255 - channel` |
| **Grayscale** | Perceptual luminance | `0.299R + 0.587G + 0.114B` |
| **Sepia** | Warm vintage tone | Standard 3×3 sepia matrix |
| **Edge Detection** | Highlights edges | 3×3 Laplacian (center=8, neighbors=−1) |
| **Gaussian Blur** | Gaussian smoothing | 3×3 kernel (weights: 4-2-1, divisor=16) |

---

## Execution Paradigms

### Sequential — Direct Mutation (`filtrossecuenciales.rkt`)

Operates on the ARGB byte-string **in-place** using `bytes-set!`. This is the closest approach to C: no intermediate allocations, no copies. Useful as a performance baseline.

```racket
(negative-sequential! pixel-bytes)   ; mutates pixel-bytes directly
```

### Recursive — Immutable Lists (`filtrosrecursivos.rkt`)

Converts the buffer into a list of pixels `(list a r g b)`, applies `map` with the transformation function, and converts back to bytes. Follows Racket's pure functional style: no side effects, immutable data.

```racket
(negative-recursive pixel-bytes)     ; returns a new byte-string
```

For convolution filters (edge, gaussian), uses a `vector` for O(1) coordinate access and mutual recursion between `process-rows` and `process-cols`.

### Parallel — Futures (`filtrosparalelos.rkt`)

Divides the work into pixel or row strips, launches one `future` per strip, and synchronizes them with `touch`. The number of workers is **configurable at runtime** from the web interface.

```racket
(set-num-workers! 8)                 ; change the thread count
(negative-parallel pixel-bytes)      ; runs with the configured workers
```

The default number of workers is `(processor-count)` (all available logical cores), with a valid range of **2 to 64**.

---

## Requirements

- [Racket](https://racket-lang.org/) **8.x** or later
- Packages included in the standard Racket installation:
  - `racket/draw` — bitmap manipulation
  - `web-server/servlet-env` — HTTP server
  - `net/base64` — Base64 encoding
  - `json` — response serialization

No external dependencies or additional `raco pkg install` commands are required.

---

## Installation & Usage

**1. Clone the repository**

```bash
git clone https://github.com/SRViche/PixelFilter-Image-Processing-Pipeline.git
```

**2. Place your test images** in the project root (the repo already includes `cat.png`, `cats2.png`, and `new-york-large.jpg` as examples).

**3. Start the server from inside the project folder**

```bash
cd pixelflow
racket htmlcontroller.rkt
```

> ⚠️ It is important to run this command **from inside the project folder**. Otherwise, the server will not find `index.html` or the image files.

**4. Open your browser**

```
http://localhost:8080
```

**5. Use the interface**

- Select an image, a filter, and an execution approach.
- If you choose **Parallel**, a slider appears to control the number of threads (2–64). A hint shows how many logical cores your machine has.
- Click **Process Buffer** and observe the output image and the measured execution time.

---

## File Structure

```
pixelflow/
│
├── htmlcontroller.rkt       # HTTP server: routing and response serialization
├── mainbase.rkt             # Processing orchestrator and time measurement
├── filtrossecuenciales.rkt  # Filters using direct mutation (sequential)
├── filtrosrecursivos.rkt    # Filters using immutable lists (recursive)
├── filtrosparalelos.rkt     # Filters using Racket futures (parallel)
│
├── index.html               # Web UI (dark mode, workers slider)
│
├── cat.png                  # Small test image
├── cats2.png                # Medium test image
└── new-york-large.jpg       # Large test image
```

---

## API Reference

### `POST /api/process`

Processes an image and returns the result in Base64.

**Request body (JSON):**

| Field | Type | Required | Description |
|---|---|---|---|
| `image` | `string` | ✅ | File name (e.g. `"cat.png"`) |
| `filter` | `string` | ✅ | `"negative"` · `"grayscale"` · `"sepia"` · `"edge"` · `"gaussian"` |
| `approach` | `string` | ✅ | `"sequential"` · `"recursive"` · `"parallel"` |
| `workers` | `integer` | ❌ | Thread count (2–64). Only applies when `approach = "parallel"` |

**Response body (JSON):**

| Field | Type | Description |
|---|---|---|
| `base64Image` | `string` | Processed PNG image encoded in Base64 |
| `timeMs` | `integer` | Real execution time in milliseconds |

**Example:**

```bash
curl -X POST http://localhost:8080/api/process \
  -H "Content-Type: application/json" \
  -d '{"image":"cat.png","filter":"grayscale","approach":"parallel","workers":8}'
```

**Response codes:**

| Code | Meaning |
|---|---|
| `200` | Successful processing |
| `404` | Image file not found |
| `500` | Internal server error |

All responses include `Access-Control-Allow-Origin: *` headers.
