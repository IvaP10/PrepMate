from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata


ROOT = Path(SPECPATH).resolve().parent
datas = [
    (str(ROOT / "local_schema.sql"), "."),
]
migrations = ROOT / "local_migrations"
datas.extend(
    (str(path), "local_migrations")
    for path in sorted(migrations.glob("*.sql"))
)
binaries = []
hiddenimports = [
    "keyring.backends.macOS",
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

for package in (
    "cryptography",
    "docx",
    "fastapi",
    "pypdfium2",
    "httpx",
    "jsonschema",
    "keyring",
    "openai",
    "pydantic",
    "uvicorn",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

for distribution in ("keyring", "openai"):
    try:
        datas += copy_metadata(distribution)
    except Exception:
        pass

# jsonschema can use this optional URI-format checker when it is present in a
# build environment. Its grammar is a package data file rather than Python
# bytecode, so include it to keep frozen startup deterministic.
try:
    datas += collect_data_files("rfc3987_syntax")
except Exception:
    pass

a = Analysis(
    [str(ROOT / "desktop_backend.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # The core desktop build intentionally excludes the optional OCR/ML pack
    # and unrelated packages that may be installed in a developer's Python
    # environment.  Resume OCR remains a graceful source-runtime fallback and
    # is distributed separately through requirements-ocr.lock.txt.
    excludes=[
        "paddleocr",
        "paddle",
        "paddlepaddle",
        "numpy",
        "PIL",
        "tensorflow",
        "tensorflow_datasets",
        "keras",
        "torch",
        "torchvision",
        "torchaudio",
        "transformers",
        "datasets",
        "IPython",
        "jedi",
        "parso",
        "zmq",
        "tkinter",
        "babel",
        "pytz",
        "spacy",
        "thinc",
        "nltk",
        "cv2",
        "onnx",
        "onnxruntime",
        "pyarrow",
        "scipy",
        "sklearn",
        "pandas",
        "matplotlib",
        "gradio",
        "boto3",
        "botocore",
        "google.cloud",
        "google.auth",
        "faiss",
        "sentencepiece",
        "soundfile",
        "sounddevice",
        "pydub",
        "emoji",
        "timm",
        "huggingface_hub",
        "hf_xet",
        "srsly",
        "langcodes",
        "marisa_trie",
        "mysql",
        "psycopg2",
        "sqlalchemy",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="prepmate-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="prepmate-backend",
)
