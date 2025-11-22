import fs from "fs";
import OpenAI from "openai";
import NodeCache from "node-cache";
import { ask } from "../config/genai.js";
import { Course } from "../models/Course.model.js";
import { VoiceSession } from "../models/VoiceSession.model.js";

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
const courseCache = new NodeCache({ stdTTL: 600 }); // Cache courses for 10 minutes
const DEFAULT_VOICE = "alloy";
const CHEERFUL_GREETINGS = [
  "Hanji! So good to hear from you.",
  "Hey champ! Always pumped to help you out.",
  "Namaste yaar! Let's crack this together.",
  "What’s up legend! Ready when you are.",
];

function pickGreeting() {
  return CHEERFUL_GREETINGS[Math.floor(Math.random() * CHEERFUL_GREETINGS.length)] ?? CHEERFUL_GREETINGS[0];
}

function isLikelyCodeIntent(text = "") {
  if (!text) return false;
  const lowered = text.toLowerCase();
  const codeKeywords = [
    "code",
    "snippet",
    "syntax",
    "bug",
    "error",
    "function",
    "class",
    "component",
    "loop",
    "api",
    "request",
    "database",
    "stack trace",
  ];
  const hasKeyword = codeKeywords.some((kw) => lowered.includes(kw));
  const hasSymbols = /[`{}<>;=()\[\]]/.test(text);
  const hasIndentation = /\n\s{2,}/.test(text);
  return hasKeyword || hasSymbols || hasIndentation;
}

export const voiceChat = async (req, res) => {
  let audioFilePath;
  try {
    const user = req.user;
    const { courseId, voice = DEFAULT_VOICE, quality = "mini" } = req.body || {};

    if (!user?._id) {
      return res.status(401).json({ message: "Please log in to continue." });
    }

    if (!req.file) {
      return res.status(400).json({ message: "I didn't catch any audio. Mind trying again?" });
    }

    if (!courseId) {
      return res.status(400).json({ message: "Pick a course so I can give you the right context." });
    }

    // Check cache for course
    let course = courseCache.get(courseId);
    if (!course) {
      course = await Course.findOne({ courseId });
      if (course) {
        courseCache.set(courseId, course);
      }
    }

    if (!course || !course.isActive) {
      return res.status(404).json({ message: "That course looks inactive. Try another one?" });
    }

    audioFilePath = req.file.path;

    const transcription = await openai.audio.transcriptions.create({
      file: fs.createReadStream(audioFilePath),
      model: process.env.OPENAI_TRANSCRIBE_MODEL || "whisper-1",
    });

    const transcriptText = transcription?.text?.trim?.() || "";
    if (!transcriptText) {
      return res.status(400).json({ message: "I couldn’t quite hear that—could you speak up and retry?" });
    }

    const codeIntent = isLikelyCodeIntent(transcriptText);

    const targetModel = quality === "high" ? "gpt-4.1" : process.env.OPENAI_MODEL || "gpt-4.1-mini";
    const { answer } = await ask(transcriptText, {
      courseName: course.name,
      collectionName: course.qdrantCollection,
      model: targetModel,
    });

    const cleanedAnswer = (answer || "Let me think about that and get back to you.").trim();

    let replyType = "audio";
    let audioBase64 = null;
    let voiceGreeting = null;

    if (codeIntent) {
      replyType = "text";
    } else {
      voiceGreeting = pickGreeting();
      const voiceInput = `${voiceGreeting} ${cleanedAnswer}`;
      const speech = await openai.audio.speech.create({
        model: process.env.OPENAI_TTS_MODEL || "gpt-4o-mini-tts",
        voice,
        input: voiceInput,
        format: "mp3",
      });
      const buffer = Buffer.from(await speech.arrayBuffer());
      audioBase64 = `data:audio/mpeg;base64,${buffer.toString("base64")}`;
    }

    // Non-blocking logging
    VoiceSession.create({
      userId: user._id,
      courseId: course.courseId,
      transcript: transcriptText,
      answer: cleanedAnswer,
      responseType: replyType,
      meta: {
        voice,
        model: targetModel,
        greeting: voiceGreeting,
        codeIntent,
      },
    }).catch(err => console.warn("VoiceSession log failed", err.message));

    const payload = {
      transcript: transcriptText,
      text: cleanedAnswer,
      replyType,
      audio: replyType === "audio" ? audioBase64 : null,
      greeting: voiceGreeting,
      quota: req.rateLimit ?? null,
      meta: {
        course: course.courseId,
        voice: replyType === "audio" ? voice : null,
        model: targetModel,
        codeIntent,
      },
    };

    return res.json(payload);
  } catch (err) {
    console.error("voiceChat error:", err);
    return res.status(500).json({
      message: "Our voice agent stumbled. Give me a quick moment and try again?",
      error: process.env.NODE_ENV === "development" ? err.message : undefined,
    });
  } finally {
    if (audioFilePath) {
      // Async unlink to prevent blocking
      fs.promises.unlink(audioFilePath).catch(() => { });
    }
  }
};
