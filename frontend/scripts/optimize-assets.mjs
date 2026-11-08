import sharp from "sharp";
import { copyFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const dir = new URL("../public/assets/", import.meta.url);
const results = [];
for (const name of [
  "clans-night",
  "clans-day",
  "home-paw-dark",
  "home-paw-light",
  "afribit-mark",
]) {
  const input = new URL(name + ".png", dir),
    output = new URL(name + ".webp", dir);
  await sharp(fileURLToPath(input))
    .resize({
      width: name.startsWith("home-paw")
        ? 512
        : name === "afribit-mark"
          ? 160
          : 1080,
      withoutEnlargement: true,
    })
    .webp({ quality: 82, effort: 6 })
    .toFile(fileURLToPath(output));
  results.push({
    name,
    before: (await stat(input)).size,
    after: (await stat(output)).size,
  });
}
for (const pkg of ["sora", "space-grotesk"]) {
  const root = new URL(
    "../node_modules/@fontsource-variable/" + pkg + "/",
    import.meta.url,
  );
  await copyFile(
    new URL("files/" + pkg + "-latin-wght-normal.woff2", root),
    new URL("fonts/" + pkg + "-latin-variable.woff2", dir),
  );
  await copyFile(
    new URL("LICENSE", root),
    new URL("../licenses/" + pkg + ".txt", dir),
  );
}
console.log(JSON.stringify(results, null, 2));
