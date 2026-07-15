import { request } from "@playwright/test"
import fs from "node:fs/promises"
import path from "node:path"

const generated = path.join(__dirname, ".generated")

async function writeMediaFixtures() {
  await fs.mkdir(generated, { recursive: true })
  const sampleRate = 16_000
  const samples = sampleRate
  const wav = Buffer.alloc(44 + samples * 2)
  wav.write("RIFF", 0)
  wav.writeUInt32LE(wav.length - 8, 4)
  wav.write("WAVEfmt ", 8)
  wav.writeUInt32LE(16, 16)
  wav.writeUInt16LE(1, 20)
  wav.writeUInt16LE(1, 22)
  wav.writeUInt32LE(sampleRate, 24)
  wav.writeUInt32LE(sampleRate * 2, 28)
  wav.writeUInt16LE(2, 32)
  wav.writeUInt16LE(16, 34)
  wav.write("data", 36)
  wav.writeUInt32LE(samples * 2, 40)
  for (let index = 0; index < samples; index += 1) {
    wav.writeInt16LE(Math.round(Math.sin(index / 16) * 1200), 44 + index * 2)
  }
  await fs.writeFile(path.join(generated, "audio.wav"), wav)

  const width = 320
  const height = 240
  const frame = Buffer.concat([
    Buffer.alloc(width * height, 96),
    Buffer.alloc((width * height) / 4, 128),
    Buffer.alloc((width * height) / 4, 128),
  ])
  const chunks: Buffer[] = [Buffer.from(`YUV4MPEG2 W${width} H${height} F30:1 Ip A1:1 C420jpeg\n`)]
  for (let index = 0; index < 30; index += 1) chunks.push(Buffer.from("FRAME\n"), frame)
  await fs.writeFile(path.join(generated, "video.y4m"), Buffer.concat(chunks))
}

export default async function globalSetup() {
  await writeMediaFixtures()
  if (process.env.E2E_REQUIRE_AUTH !== "true") return
  const email = process.env.E2E_EMAIL
  const password = process.env.E2E_PASSWORD
  const baseURL = process.env.E2E_BASE_URL
  const apiBaseURL = process.env.E2E_API_BASE_URL || baseURL
  const requiredFixtures = [
    "E2E_INTERVIEW_ID", "E2E_TECHNICAL_ID", "E2E_REPORT_ID",
    "E2E_MISSION_ID", "E2E_ROADMAP_NODE_ID", "E2E_EXERCISE_ID",
  ]
  const missing = requiredFixtures.filter((name) => !process.env[name])
  const missingAuth = [!email && "E2E_EMAIL", !password && "E2E_PASSWORD", !baseURL && "E2E_BASE_URL"].filter(Boolean)
  if (missingAuth.length || missing.length) {
    throw new Error(`Release browser fixtures are incomplete: ${[...missingAuth, ...missing].join(", ")}`)
  }
  const context = await request.newContext({ baseURL: apiBaseURL })
  const response = await context.post("/api/auth/login", { data: { email, password } })
  if (!response.ok()) throw new Error(`E2E login failed with HTTP ${response.status()}`)
  await context.storageState({ path: path.join(generated, "auth.json") })
  await context.dispose()
}
