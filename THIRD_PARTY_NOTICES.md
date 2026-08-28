# Third-party notices

PrepMate is distributed under Apache-2.0. Its dependency graph contains
software under additional open-source licenses. Release SBOMs are the
authoritative version-specific inventory; this file highlights material
runtime components and is not a replacement for their license texts.

| Component | Purpose | License family |
| --- | --- | --- |
| pypdfium2 / PDFium | PDF text extraction and rendering | Apache-2.0 / BSD-style; retain bundled dependency notices |
| PaddleOCR / PaddlePaddle | Optional scanned-PDF OCR pack | Apache-2.0 |
| FastAPI / Uvicorn | Local API | MIT / BSD-style |
| cryptography | Local field encryption | Apache-2.0 or BSD |
| Electron | Desktop shell | MIT |
| Next.js / React | Renderer | MIT |

Provider SDKs and API access remain subject to the selected provider's terms.
Contributors adding or updating a dependency must verify its license, update
this file when material, and ensure the release SBOM and bundled license files
remain complete.
