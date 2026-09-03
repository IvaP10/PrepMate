import {
  cp,
  mkdir,
  readdir,
  rename,
  rmdir,
  stat,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputDirectory = path.join(projectRoot, "dist", "client");

const publicBasePath =
  process.env.NEXT_PUBLIC_BASE_PATH?.trim().replace(/^\/+|\/+$/g, "") || "";
if (publicBasePath) {
  const prefixedOutputDirectory = path.join(
    outputDirectory,
    ...publicBasePath.split("/").filter(Boolean),
  );
  try {
    const prefixedEntries = await readdir(prefixedOutputDirectory, {
      withFileTypes: true,
    });
    await Promise.all(
      prefixedEntries.map((entry) =>
        rename(
          path.join(prefixedOutputDirectory, entry.name),
          path.join(outputDirectory, entry.name),
        ),
      ),
    );
    await rmdir(prefixedOutputDirectory);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

const entries = await readdir(outputDirectory, { withFileTypes: true });

await Promise.all(
  entries
    .filter(
      (entry) =>
        entry.isFile() &&
        entry.name.endsWith(".html") &&
        entry.name !== "404.html" &&
        entry.name !== "index.html",
    )
    .map(async (entry) => {
      const routeName = entry.name.slice(0, -".html".length);
      const routeDirectory = path.join(outputDirectory, routeName);
      try {
        await mkdir(routeDirectory, { recursive: true });
      } catch (error) {
        const existingEntry = await stat(routeDirectory).catch(() => null);
        if (error?.code !== "EEXIST" || !existingEntry?.isFile()) throw error;
        return;
      }
      await cp(
        path.join(outputDirectory, entry.name),
        path.join(routeDirectory, "index.html"),
      );
    }),
);

await writeFile(path.join(outputDirectory, ".nojekyll"), "");
