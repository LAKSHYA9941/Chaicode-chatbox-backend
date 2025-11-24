import { QdrantClient } from "@qdrant/js-client-rest";
import "dotenv/config";

console.log("Testing QdrantClient with checkCompatibility: false...");

const client = new QdrantClient({ 
  url: "https://qdrant-deployment-vsci.onrender.com", 
  port: 443,
  checkCompatibility: false
});

try {
    const result = await client.getCollections();
    console.log("✅ Success! Connected via QdrantClient.");
    console.log("Collections:", result.collections.map(c => c.name).join(", ") || "None");
} catch (e) {
    console.error("❌ Connection failed:", e.message);
    if (e.cause) console.error("Cause:", e.cause);
}
