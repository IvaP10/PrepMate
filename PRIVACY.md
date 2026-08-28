# PrepMate privacy boundary

PrepMate is a local-first macOS application. It does not require a PrepMate
account and does not send application data to a PrepMate-operated server.
Before the user configures an AI provider, the app makes only loopback requests
to its own desktop services; there is no analytics, telemetry, automatic update
check, hosted application request, or browser edition of PrepMate.

## Stored on the device

PrepMate stores preferences, resumes, job descriptions, interview state,
transcripts, technical attempts, reports, Performance evidence, and Improve
progress in its application-data directory. Sensitive fields are encrypted
with AES-GCM. The encryption key and provider API keys are stored separately in
the operating-system keychain.

The application does not include analytics, advertising, payment, or tracking
SDKs.

## Data sent off the device

When an AI feature is used, the application sends the minimum prompt context
needed for that feature directly to the provider selected in Settings. This
can include resume-derived professional context, job descriptions, interview
questions and answers, transcript excerpts, technical reasoning, and report or
coaching inputs. Direct identifiers are redacted on a best-effort basis before
text-model calls, but users should assume the selected provider processes the
submitted content under that provider's own terms and retention policy.

OpenAI voice transcription uploads the selected audio segment to OpenAI. Other
configured text providers do not currently provide the voice transcription
path.

Camera coaching is processed in the renderer and does not download a vision
model or upload camera frames. The application does not download speech or
vision models and does not include interviewer text-to-speech.

## Local code execution

Technical-round code runs locally only through the macOS Seatbelt sandbox. The
sandbox denies network access and access to user files outside its temporary
working directory. If the sandbox is unavailable, execution is disabled.

## Export and deletion

The profile export endpoint creates a local JSON representation while omitting
hidden evaluator cases. Deleting resumes removes source resume versions,
profile data, and saved setup snapshots; past interview reports and derived
session evidence remain until interview history is deleted. Uninstallers
preserve application data by default to avoid accidental loss; use the complete
wipe control or remove the PrepMate application-data directory and keychain
entries when a full reset is desired.

Back up exported data carefully: exports are readable JSON and are not
encrypted by PrepMate after export.

## Backups and key loss

Automatic pre-migration backups are raw SQLite snapshots. Fields encrypted in
the active database remain encrypted with the same operating-system keychain
key, but a backup created while upgrading an older schema can retain legacy
plaintext columns. Treat the entire backup directory as sensitive and remove
obsolete migration backups after verifying the upgrade. If the key is deleted,
reset, or unavailable, encrypted content cannot be recovered. A readable JSON
export is the portable backup format, but it must be protected separately
because it is not encrypted.
