const { app, BrowserWindow, dialog, ipcMain, session, shell } = require("electron")
const { randomBytes } = require("node:crypto")
const { spawn } = require("node:child_process")
const http = require("node:http")
const net = require("node:net")
const path = require("node:path")

const isDevelopment = !app.isPackaged
app.setName("PrepMate")
let apiProcess = null
let frontendProcess = null
let mainWindow = null
let shuttingDown = false

ipcMain.handle("prepmate:open-data-folder", async () => {
  try {
    const error = await shell.openPath(app.getPath("userData"))
    return error ? { success: false, error } : { success: true }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : String(error) }
  }
})

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.once("error", reject)
    server.listen(0, "127.0.0.1", () => {
      const address = server.address()
      const port = typeof address === "object" && address ? address.port : 0
      server.close((error) => error ? reject(error) : resolve(port))
    })
  })
}

function waitFor(url, timeoutMs = 45_000) {
  const started = Date.now()
  return new Promise((resolve, reject) => {
    const poll = () => {
      const request = http.get(url, (response) => {
        response.resume()
        if (response.statusCode && response.statusCode < 500) {
          resolve()
          return
        }
        retry()
      })
      request.setTimeout(1_500, () => request.destroy())
      request.on("error", retry)
    }
    const retry = () => {
      if (Date.now() - started >= timeoutMs) {
        reject(new Error(`Timed out waiting for ${url}`))
      } else {
        setTimeout(poll, 250)
      }
    }
    poll()
  })
}

function childEnvironment(extra = {}) {
  return {
    ...process.env,
    ...extra,
    ENVIRONMENT: "production",
    DEVELOPMENT_AUTO_WORKER: "true",
    PREPMATE_DATA_DIR: app.getPath("userData"),
  }
}

function startApi(port, token) {
  if (isDevelopment) {
    const root = path.resolve(__dirname, "../..")
    return spawn(
      process.env.PREPMATE_PYTHON || process.env.INTERAI_PYTHON || "python3",
      ["-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", String(port)],
      {
        cwd: root,
        env: childEnvironment({ PORT: String(port), PREPMATE_API_TOKEN: token }),
        stdio: "inherit",
      },
    )
  }

  const executable = process.platform === "win32" ? "prepmate-backend.exe" : "prepmate-backend"
  return spawn(path.join(process.resourcesPath, "backend", executable), [], {
    cwd: path.join(process.resourcesPath, "backend"),
    env: childEnvironment({ PORT: String(port), PREPMATE_API_TOKEN: token }),
    stdio: "ignore",
    windowsHide: true,
  })
}

function startFrontend(port, apiBaseUrl, token) {
  if (isDevelopment) {
    const root = path.resolve(__dirname, "../..")
    const npmExecutable = process.platform === "win32" ? "npm.cmd" : "npm"
    return spawn(
      npmExecutable,
      ["run", "dev:renderer", "--", "--hostname", "127.0.0.1", "--port", String(port)],
      {
        cwd: path.join(root, "Frontend"),
        env: childEnvironment({
          DEV_API_PROXY_TARGET: apiBaseUrl,
          PREPMATE_API_BASE_URL: apiBaseUrl,
          PREPMATE_DESKTOP_TOKEN: token,
        }),
        stdio: "inherit",
      },
    )
  }

  const server = path.join(process.resourcesPath, "frontend", "server.js")
  return spawn(process.execPath, [server], {
    cwd: path.dirname(server),
    env: childEnvironment({
      ELECTRON_RUN_AS_NODE: "1",
      HOSTNAME: "127.0.0.1",
      PORT: String(port),
      PREPMATE_API_BASE_URL: apiBaseUrl,
      PREPMATE_DESKTOP_TOKEN: token,
    }),
    stdio: "ignore",
    windowsHide: true,
  })
}

function terminate(child) {
  if (!child || child.killed) return
  try {
    child.kill("SIGTERM")
  } catch {
    // Process may already have exited.
  }
}

function sameOrigin(candidate, expectedOrigin) {
  try {
    return new URL(candidate).origin === expectedOrigin
  } catch {
    return false
  }
}

function configureSession(apiBaseUrl, token, frontendOrigin) {
  session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
    const headers = { ...details.requestHeaders }
    if (details.url.startsWith(`${apiBaseUrl}/`)) headers["X-PrepMate-Token"] = token
    if (sameOrigin(details.url, frontendOrigin)) headers["X-PrepMate-Desktop-Token"] = token
    callback({ requestHeaders: headers })
  })

  const allowedOrigin = new URL(frontendOrigin).origin
  session.defaultSession.setPermissionCheckHandler((_webContents, permission, requestingOrigin) => {
    return requestingOrigin === allowedOrigin && ["media", "display-capture"].includes(permission)
  })
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    const origin = new URL(webContents.getURL()).origin
    callback(origin === allowedOrigin && ["media", "display-capture"].includes(permission))
  })
}

async function createWindow(frontendUrl, apiBaseUrl) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    backgroundColor: "#090909",
    title: "PrepMate",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, "preload.cjs"),
      additionalArguments: [`--prepmate-api-base=${apiBaseUrl}`],
    },
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) void shell.openExternal(url)
    return { action: "deny" }
  })
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!sameOrigin(url, new URL(frontendUrl).origin)) event.preventDefault()
  })
  mainWindow.once("ready-to-show", () => mainWindow?.show())
  mainWindow.on("closed", () => { mainWindow = null })
  await mainWindow.loadURL(frontendUrl)
}

async function boot() {
  if (isDevelopment && process.platform === "darwin") {
    app.dock.setIcon(path.resolve(__dirname, "../assets/icon.png"))
  }

  const apiPort = await freePort()
  let frontendPort = await freePort()
  while (frontendPort === apiPort) frontendPort = await freePort()
  const apiBaseUrl = `http://127.0.0.1:${apiPort}`
  const frontendUrl = `http://127.0.0.1:${frontendPort}`
  const token = randomBytes(32).toString("base64url")

  configureSession(apiBaseUrl, token, frontendUrl)
  apiProcess = startApi(apiPort, token)
  apiProcess.once("exit", (code) => {
    if (!shuttingDown) void dialog.showErrorBox("PrepMate stopped", `The local service exited unexpectedly (${code ?? "unknown"}).`)
  })
  frontendProcess = startFrontend(frontendPort, apiBaseUrl, token)
  frontendProcess.once("exit", (code) => {
    if (!shuttingDown) void dialog.showErrorBox("PrepMate stopped", `The desktop renderer exited unexpectedly (${code ?? "unknown"}).`)
  })
  await Promise.all([
    waitFor(`${apiBaseUrl}/live`),
    waitFor(frontendUrl),
  ])
  await createWindow(frontendUrl, apiBaseUrl)
}

const hasInstanceLock = app.requestSingleInstanceLock()
if (!hasInstanceLock) app.quit()

app.on("second-instance", () => {
  if (!mainWindow) return
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.focus()
})

app.whenReady().then(boot).catch((error) => {
  dialog.showErrorBox("PrepMate could not start", error instanceof Error ? error.message : String(error))
  app.quit()
})

app.on("activate", () => {
  if (mainWindow) mainWindow.show()
})

app.on("before-quit", () => {
  shuttingDown = true
  terminate(frontendProcess)
  terminate(apiProcess)
})

app.on("window-all-closed", () => app.quit())
