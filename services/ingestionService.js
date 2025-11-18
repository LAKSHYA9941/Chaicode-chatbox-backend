import "dotenv/config";
import fs from "fs";
import path from "path";
import webvtt from "node-webvtt";
import { QdrantClient } from "@qdrant/js-client-rest";
import { QdrantVectorStore } from "@langchain/community/vectorstores/qdrant";
import { RecursiveCharacterTextSplitter } from "langchain/text_splitter";
import { OpenAIEmbeddings } from "@langchain/openai";
import { Document } from "@langchain/core/documents";

const QDRANT_URL = process.env.QDRANT_URL || "http://localhost:6333";
const EMBEDDING_MODEL = process.env.OPENAI_EMBEDDING_MODEL || "text-embedding-3-small"; // 1536
const EMBEDDING_DIMS = Number(process.env.OPENAI_EMBEDDING_DIMS || 1536);

const client = new QdrantClient({ url: QDRANT_URL });
const embeddings = new OpenAIEmbeddings({ apiKey: process.env.OPENAI_API_KEY, model: EMBEDDING_MODEL });

async function ensureCollection(collectionName, { forceRecreate = false } = {}) {
  let needsCreate = false;

  if (forceRecreate) {
    try {
      await client.deleteCollection(collectionName);
      console.info(`🔁 Recreating Qdrant collection "${collectionName}" as requested.`);
    } catch (err) {
      if (err?.status && err.status !== 404) throw err;
    }
    needsCreate = true;
  }

  if (!forceRecreate) {
    try {
      const info = await client.getCollection(collectionName);
      const currentSize = info?.result?.config?.params?.vectors?.size;
      if (currentSize && Number(currentSize) !== EMBEDDING_DIMS) {
        console.warn(
          `Recreating Qdrant collection "${collectionName}" due to vector size mismatch (existing: ${currentSize}, expected: ${EMBEDDING_DIMS}).`
        );
        await client.deleteCollection(collectionName);
        needsCreate = true;
      }
    } catch (err) {
      if (err?.status === 404) {
        needsCreate = true;
      } else {
        throw err;
      }
    }
  }

  if (needsCreate) {
    await client.createCollection(collectionName, {
      vectors: { size: EMBEDDING_DIMS, distance: "Cosine" },
    });
  }
}

function parseVttContent(content) {
  const parsed = webvtt.parse(content, { strict: false });
  const text = parsed.cues.map((c) => (c.text || "").trim()).filter(Boolean).join("\n");
  return text;
}

const splitter = new RecursiveCharacterTextSplitter({
  chunkSize: 400,
  chunkOverlap: 60,
  separators: ["\n\n", "\n", " ", ""],
});

export async function ingestVttFiles({ course, files, forceRecreate = false, onProgress } = {}) {
  if (!course?.qdrantCollection) throw new Error("course.qdrantCollection required");

  await ensureCollection(course.qdrantCollection, { forceRecreate });
  const vectorStore = await QdrantVectorStore.fromExistingCollection(embeddings, {
    client,
    collectionName: course.qdrantCollection,
  });

  let totalDocs = 0;
  let processedFiles = 0;
  const totalFiles = files.length;
  const reporter = typeof onProgress === "function" ? onProgress : async () => {};

  for (const f of files) {
    const filePath = f.path; // multer path
    const raw = fs.readFileSync(filePath, "utf8");
    const text = parseVttContent(raw);
    if (!text.trim()) continue;

    processedFiles += 1;
    const fileName = f.originalname || f.filename || path.basename(f.path || `file-${processedFiles}.vtt`);
    const docs = await splitter.createDocuments([text], [
      { courseId: course.courseId, file: path.basename(f.originalname || f.filename || f.path) },
    ]);

    if (docs.length > 0) {
      await vectorStore.addDocuments(
        docs.map((d) => new Document({ pageContent: d.pageContent, metadata: d.metadata }))
      );
      totalDocs += docs.length;
    }

    console.info(
      `[ingest] ${course.courseId}: processed ${processedFiles}/${totalFiles} -> ${fileName} (${docs.length} chunks, total ${totalDocs})`
    );
    await reporter({
      courseId: course.courseId,
      fileIndex: processedFiles,
      totalFiles,
      fileName,
      docs: docs.length,
      totalDocs,
      timestamp: new Date().toISOString(),
    });
  }

  await reporter({
    courseId: course.courseId,
    fileIndex: processedFiles,
    totalFiles,
    fileName: null,
    docs: 0,
    totalDocs,
    done: true,
    timestamp: new Date().toISOString(),
  });

  return { upserted: totalDocs, processedFiles, totalFiles };
}
