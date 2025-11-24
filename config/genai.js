import "dotenv/config";
import { QdrantClient } from "@qdrant/js-client-rest";
import { QdrantVectorStore } from "@langchain/community/vectorstores/qdrant";
import { OpenAIEmbeddings } from "@langchain/openai";
import OpenAI from "openai";

// ---------- shared instances ----------
const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

// OpenAI embeddings: must match ingestion dimensions
const baseEmbeddings = new OpenAIEmbeddings({
  apiKey: process.env.OPENAI_API_KEY,
  model: process.env.OPENAI_EMBEDDING_MODEL || "text-embedding-3-small", // 1536-dim
});

const url = process.env.QDRANT_URL || "http://localhost:6333";
export const client = new QdrantClient({
  url,
  port: url.startsWith("https") ? 443 : 6333,
  checkCompatibility: false,
});

// ---------- ready-to-use ask() for the front-end ----------

export async function ask(query, opts = {}) {
  const { courseName = "", collectionName, model } = opts;
  const embeddings = baseEmbeddings; // alias
  if (!collectionName) {
    throw new Error("collectionName is required for retrieval");
  }

  // Retrieve relevant context from Qdrant (cost-efficient, no heavy chains)
  const vectorStore = await QdrantVectorStore.fromExistingCollection(embeddings, {
    client,
    collectionName,
  });
  let docs = [];
  try {
    docs = await vectorStore.similaritySearch(query, 4);
  } catch (error) {
    const apiErrorMessage = error?.data?.status?.error || error?.message || "";
    if (typeof apiErrorMessage === "string" && apiErrorMessage.includes("Vector dimension error")) {
      const mismatchError = new Error("QDRANT_DIMENSION_MISMATCH");
      mismatchError.code = "QDRANT_DIMENSION_MISMATCH";
      mismatchError.details = { message: apiErrorMessage };
      throw mismatchError;
    }
    throw error;
  }
  const context = docs.map((d) => d.pageContent).join("\n\n").slice(0, 3000);

  const systemPrompt = `You are Hitesh Choudhary, a passionate Indian MERN stack educator, mentor, and motivator.
1-You sometimes start with "Hanji!".
2-Explain in simple, short, practical Hinglish (Hindi + English).
3-break code into steps if intent is to write code, add motivational advice, keep tone friendly, witty, informal , be short and concise about the answers.
4-Answer as an expert in the ${courseName} course and refrain from answering questions outside the scope of the course for example if ${courseName} is about python then do not answer questions related to nodejs also suggest the user to switch to the relevant course in any situation do not answer these types of questions.
5-Avoid academic jargon—talk like a friend over tea and dont talk unnecessarily keep it short and simple for every response untill not asked to explain something in detail.
6-Give concise but helpful answers with examples and code snippets where relevant.
7-If asked about cost, respond with this link "https://hitesh.ai" or "https://www.chaicode.com".
`
    ;

  const userPrompt = `Context (from course materials):\n${context}\n\nQuestion: ${query}`;

  const chosenModel = model || process.env.OPENAI_MODEL || "gpt-4.1-mini"; // default to mini for cost
  const completion = await openai.chat.completions.create({
    model: chosenModel,
    temperature: 0.2,
    max_tokens: 500,
    messages: [
      { role: "system", content: systemPrompt },
      { role: "user", content: userPrompt },
    ],
  });

  const text = completion?.choices?.[0]?.message?.content || "";
  return { answer: text.trim() };
}