// dim.js
import "dotenv/config";
import { GoogleGenerativeAIEmbeddings } from "@langchain/google-genai";

const e = new GoogleGenerativeAIEmbeddings({ model: "gemini-embedding-001" });
console.log("Dimension:", (await e.embedQuery("test")).length);