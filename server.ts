import dotenv from 'dotenv';
dotenv.config();

import express from 'express';
import { GoogleGenAI } from '@google/genai';
import { Pool } from 'pg';
import path from 'path';
import { createServer as createViteServer } from 'vite';


const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: false 
});

async function initializeDatabase() {
  const createTableQuery = `
    CREATE TABLE IF NOT EXISTS food_scans (
      id SERIAL PRIMARY KEY,
      food_data TEXT,
      created_at TIMESTAMP DEFAULT NOW()
    );
  `;
  try {
    await pool.query(createTableQuery);
    await pool.query(`ALTER TABLE food_scans ADD COLUMN IF NOT EXISTS food_data TEXT;`);
    await pool.query(`ALTER TABLE food_scans ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();`);
  } catch (error) {
    console.error("Could not create table:", error);
  }
}
initializeDatabase();

const app = express();
app.use(express.json({ limit: '50mb' })); 
app.use(express.urlencoded({ limit: '50mb', extended: true }));
app.use(express.text({ limit: '50mb' }));

async function analyzeFoodImage(base64Data: string) {
  const response = await ai.models.generateContent({
    model: 'gemini-2.5-flash',
    contents: [
      {
        role: 'user',
        parts: [
          { text: 'Analyze this food. Return ONLY a valid JSON object with EXACTLY these keys: "calories", "protein", "carbs", "fats". The values should be numbers or short strings (e.g., "105", "1.3g"). Do NOT include markdown or any other text.' },
          {
            inlineData: {
              data: base64Data,
              mimeType: 'image/jpeg' 
            }
          }
        ]
      }
    ],
    config: {
      responseMimeType: "application/json"
    }
  });
  if (response.text) {
      return JSON.parse(response.text);
  }
  return { calories: "N/A", protein: "N/A", carbs: "N/A", fats: "N/A" };
}

app.post("/api/analyze", async (req, res) => {
  try {
    const body = req.body || {};
    let rawImage = typeof body === 'string' 
      ? body 
      : (body.imageBase64 || body.image || body.file || body.dataUrl || body.data);

    if (!rawImage || typeof rawImage !== 'string') {
      return res.status(400).json({ error: "No valid image data found in request." });
    }

    const cleanBase64Image = rawImage.includes(',') 
      ? rawImage.split(',')[1] 
      : rawImage;

    console.log("Analyzing image with Gemini...");
    
    const nutrition = await analyzeFoodImage(cleanBase64Image);
    
    console.log("Saving to PostgreSQL database...");
    const insertQuery = `
      INSERT INTO food_scans (food_data, created_at) 
      VALUES ($1, NOW()) 
      RETURNING *;
    `;
    await pool.query(insertQuery, [JSON.stringify(nutrition)]);
    console.log("Successfully saved!");
    res.json(nutrition);

  } catch (error) {
    console.error("Error analyzing image:", error);
    res.status(500).json({ 
      error: error instanceof Error ? error.message : "Failed to analyze image" 
    });
  }
});


const PORT = Number(process.env.PORT) || 3000;

async function startServer() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
