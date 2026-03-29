import json
import logging
import os
from pathlib import Path

from google import genai
from google.genai import types

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

def generate_insights(prompt_file_path: Path, output_file_path: Path) -> bool:
    """Read prompt JSON, send to Gemini, and save the insights."""
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set. Skipping live LLM insight generation.")
        return False
        
    try:
        with open(prompt_file_path, "r", encoding="utf-8") as f:
            prompt_data = json.load(f)
            
        # The prompt is a list of messages. We'll join them or format them.
        system_instruction = ""
        user_content = ""
        for msg in prompt_data:
            if msg.get("role") == "system":
                system_instruction = msg.get("content", "")
            elif msg.get("role") == "user":
                user_content = msg.get("content", "")
                
        client = genai.Client(api_key=api_key)
        
        logger.info("Sending cross-track analysis prompt to Gemini 2.5 Flash...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2, # Keep it deterministic and factual
                response_mime_type="application/json",
            ),
        )
        
        result_text = response.text
        
        # Validate it's JSON
        parsed_json = json.loads(result_text)
        
        with open(output_file_path, "w", encoding="utf-8") as f:
            json.dump(parsed_json, f, indent=2)
            
        logger.info(f"Successfully generated insights and saved to {output_file_path.name}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to generate LLM insights: {e}")
        return False
