// ingest.js
import "dotenv/config";
import fs from "fs";
import path from "path";
import webvtt from "node-webvtt";
import { QdrantClient } from "@qdrant/js-client-rest";
// HF: removed GoogleGenerativeAIEmbeddings import
import { RecursiveCharacterTextSplitter } from "langchain/text_splitter";
import { InferenceClient } from "@huggingface/inference";   // <-- NEW
import { v4 as uuid } from "uuid";

const client = new QdrantClient({ url: "http://localhost:6333" });


const hf = new InferenceClient(process.env.HF_TOKEN);        // <-- NEW

async function embedWithHF(texts) {
  const vectors = await hf.featureExtraction({
    model: "sentence-transformers/all-MiniLM-L6-v2",
    inputs: texts,
  });

  return vectors;
}
// -----------------------------------------------------------------------------

const FOLDER = "./nodejs/01 Subtitles(01-26)";

/* ---------- splitter config ---------- */
const splitter = new RecursiveCharacterTextSplitter({
  chunkSize: 400,
  chunkOverlap: 50,
  separators: ["\n\n", "\n", " ", ""],
});

/* ---------- helpers ---------- */
function toSeconds(ts) {
  return typeof ts === "number" ? ts : 0;
}

/* ---------- main ---------- */
async function main() {
  await client.recreateCollection("courses", {
    vectors: { size: 384, distance: "Cosine" }, // HF: gte-large outputs 1024-dim
  });

  const files = fs
    .readdirSync(FOLDER)
    .filter((f) => f.toLowerCase().endsWith(".vtt"));
  console.log(`📁 Found ${files.length} .vtt files`);

  for (const file of files) {
    const filePath = path.join(FOLDER, file);
    const courseId = path.basename(file, ".vtt");
    const raw = fs.readFileSync(filePath, "utf8");

    let parsed;
    try {
      parsed = webvtt.parse(raw, { strict: false });
    } catch (e) {
      console.warn(`⚠️ [${courseId}] parse error: ${e.message}`);
      continue;
    }

    /* 1) merge all cue texts into one string with newlines */
    const fullText = parsed.cues.map((c) => c.text.trim()).join("\n");
    if (!fullText.trim()) {
      console.warn(`⚠️ [${courseId}] no text to split`);
      continue;
    }

    /* 2) split into chunks with langchain */
    const docs = await splitter.createDocuments([fullText]);
    console.log(`[${courseId}] ${docs.length} chunks`);

    /* 3) embed all chunks in one HF call */
    const texts = docs.map((d) => d.pageContent.trim()).filter((t) => t);
    if (!texts.length) {
      console.warn(`⚠️ [${courseId}] no valid chunks after split`);
      continue;
    }

    const vectors = await embedWithHF(texts);

    const points = vectors.map((vec, i) => ({
      id: uuid(),
      vector: vec,
      payload: {
        courseId,
        text: texts[i],
        startSec: null,
        endSec: null,
      },
    }));

    await client.upsert("courses", { points });
    console.log(`✅ [${courseId}] upserted ${points.length} chunks`);
  }

  console.log("🎯 All files ingested.");
}

main().catch(console.error);