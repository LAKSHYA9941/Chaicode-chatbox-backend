import fs from "fs/promises";
import path from "path";

const ROOT = path.join(process.cwd(), "nodejs");
const COST_PER_1K_TOKENS = 0.00002;
const AVG_CHARS_PER_TOKEN = 4;

async function collectVttFiles(dir) {
  const results = [];
  const entries = await fs.readdir(dir, { withFileTypes: true });

  for (const entry of entries) {
    const entryPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...(await collectVttFiles(entryPath)));
    } else if (entry.isFile() && entry.name.toLowerCase().endsWith(".vtt")) {
      results.push(entryPath);
    }
  }

  return results;
}

async function estimate() {
  const files = await collectVttFiles(ROOT);

  let totalChars = 0;
  const details = [];

  for (const filePath of files) {
    let text = "";
    try {
      text = await fs.readFile(filePath, { encoding: "utf-8" });
    } catch (error) {
      console.warn(`⚠️  Failed to read ${filePath}: ${error.message}`);
      continue;
    }

    const chars = text.length;
    const tokens = chars / AVG_CHARS_PER_TOKEN;
    totalChars += chars;

    details.push({
      file: path.relative(ROOT, filePath).replace(/\\/g, "/"),
      chars,
      tokens,
      cost: (tokens / 1000) * COST_PER_1K_TOKENS,
    });
  }

  const totalTokens = totalChars / AVG_CHARS_PER_TOKEN;
  const totalCost = (totalTokens / 1000) * COST_PER_1K_TOKENS;

  details.sort((a, b) => b.tokens - a.tokens);

  const report = {
    totalFiles: details.length,
    totalChars,
    estimatedTokens: Math.round(totalTokens),
    estimatedCostUsd: Number(totalCost.toFixed(4)),
    top10ByTokens: details.slice(0, 10).map((item) => ({
      file: item.file,
      tokens: Math.round(item.tokens),
      estimatedCostUsd: Number(item.cost.toFixed(4)),
    })),
  };

  console.log(JSON.stringify(report, null, 2));
}

estimate().catch((error) => {
  console.error("Failed to estimate ingestion cost:", error);
  process.exit(1);
});
