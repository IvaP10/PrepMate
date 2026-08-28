const { contextBridge, ipcRenderer } = require("electron")

const apiArgument = process.argv.find((value) => value.startsWith("--prepmate-api-base="))
const apiBaseUrl = apiArgument ? apiArgument.slice("--prepmate-api-base=".length) : "http://127.0.0.1:8000"

contextBridge.exposeInMainWorld("prepmateDesktop", Object.freeze({
  apiBaseUrl,
  platform: process.platform,
  version: process.env.npm_package_version || "0.1.0-alpha.1",
  openDataFolder: () => ipcRenderer.invoke("prepmate:open-data-folder"),
}))
