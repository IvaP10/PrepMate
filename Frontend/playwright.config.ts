import path from "node:path"
import { defineConfig, devices } from "@playwright/test"

const generated = path.join(__dirname, "e2e", ".generated")
const requireAuth = process.env.E2E_REQUIRE_AUTH === "true"

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: requireAuth ? 1 : undefined,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "line",
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:3100",
    storageState: requireAuth ? path.join(generated, "auth.json") : undefined,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium-desktop",
      use: {
        ...devices["Desktop Chrome"],
        permissions: ["camera", "microphone"],
        launchOptions: {
          args: [
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
            "--auto-select-desktop-capture-source=Entire screen",
            `--use-file-for-fake-audio-capture=${path.join(generated, "audio.wav")}`,
            `--use-file-for-fake-video-capture=${path.join(generated, "video.y4m")}`,
          ],
        },
      },
    },
    {
      name: "mobile-chromium",
      testMatch: /public-visual\.spec\.ts/,
      use: { ...devices["Pixel 7"] },
    },
  ],
  webServer: process.env.E2E_BASE_URL ? undefined : {
    command: "npm run dev -- --hostname 127.0.0.1 --port 3100",
    url: "http://127.0.0.1:3100",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
