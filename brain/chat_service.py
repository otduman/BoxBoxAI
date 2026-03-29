"""
Chat service for conversational coaching.

Provides a chat interface where drivers can ask questions about their
telemetry data. The LLM is strictly limited to racing coaching topics only.
"""

import json
import logging
import os
from typing import Generator

from google import genai
from google.genai import types
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# System prompt that restricts LLM to coaching topics only
COACHING_SYSTEM_PROMPT = """You are an expert racing coach AI assistant for "Pocket Race Engineer", a telemetry analysis application.

CRITICAL RULES - YOU MUST FOLLOW THESE:
1. You ONLY discuss racing, driving technique, telemetry analysis, car setup, and motorsport coaching
2. You REFUSE to discuss ANY other topics - politics, general knowledge, coding, personal advice, etc.
3. If asked about non-racing topics, respond: "I'm your racing coach - I can only help with driving technique, telemetry analysis, and car setup. What would you like to know about your lap data?"
4. You have access to the driver's session data including lap times, corner analyses, verdicts, and scoring
5. Be concise, actionable, and specific - use exact numbers from the data when available
6. Speak like a professional racing coach - direct, encouraging, focused on improvement

WHAT YOU CAN HELP WITH:
- Explaining why the driver lost time in specific corners
- Interpreting telemetry data (speeds, G-forces, brake pressure, throttle)
- Suggesting technique improvements (trail-braking, throttle application, racing line)
- Explaining physics concepts (weight transfer, tire grip, understeer/oversteer)
- Comparing laps and explaining differences
- Setup recommendations based on tire temps and balance data
- General racing strategy and racecraft

WHAT YOU CANNOT HELP WITH:
- Anything unrelated to racing/motorsport
- General conversation or chit-chat
- Other sports, hobbies, or topics
- Coding, math, or academic questions (unless directly related to racing physics)

When the driver asks a question, use the session data provided to give specific, data-backed answers.
Always reference actual numbers from their telemetry when explaining issues.
"""


def _build_session_context(session_summary: dict) -> str:
    """Build a concise context string from session data for the LLM."""
    context_parts = []

    # Basic session info
    meta = session_summary.get("session_meta", {})
    context_parts.append(f"Track: {meta.get('track_name', 'Unknown')}")
    context_parts.append(f"Laps analyzed: {meta.get('total_laps', 1)}")

    # Lap times
    laps = session_summary.get("laps", [])
    if laps:
        lap_times = [f"Lap {l.get('lap_number', i)}: {l.get('lap_time_s', 0):.2f}s"
                     for i, l in enumerate(laps)]
        context_parts.append(f"Lap times: {', '.join(lap_times)}")

    # Deterministic verdicts (top issues)
    coaching = session_summary.get("deterministic_coaching", {})
    verdicts = coaching.get("verdicts", [])
    if verdicts:
        context_parts.append(f"\nTop issues found ({len(verdicts)} total):")
        for v in verdicts[:5]:  # Top 5 verdicts
            context_parts.append(
                f"- [{v.get('segment', 'Lap')}] {v.get('category', '')}: "
                f"{v.get('finding', '')} (potential gain: {v.get('time_impact_s', 0):.2f}s)"
            )

    # Top 3 actions
    top_actions = coaching.get("top_3_actions", [])
    if top_actions:
        context_parts.append(f"\nTop 3 recommended actions:")
        for i, action in enumerate(top_actions, 1):
            # Truncate long actions
            action_short = action[:200] + "..." if len(action) > 200 else action
            context_parts.append(f"{i}. {action_short}")

    # Scoring summary
    scoring = session_summary.get("scoring", {})
    lap_scores = scoring.get("lap_scores", {})
    if lap_scores:
        context_parts.append(f"\nLap scores:")
        for lap_num, score_data in lap_scores.items():
            lap_score = score_data.get("lap_score", 0)
            context_parts.append(f"- Lap {lap_num}: {lap_score:.3f}")

            # Segment breakdown
            segments = score_data.get("segment_scores", [])
            weak_segments = [s for s in segments if s.get("score", 1) < 0.8]
            if weak_segments:
                for seg in weak_segments[:3]:
                    context_parts.append(
                        f"  - {seg.get('segment_id')}: {seg.get('score', 0):.2f} "
                        f"({seg.get('quality', 'unknown')}, issue: {seg.get('main_issue', 'none')})"
                    )

    # Corner analyses summary
    corners = session_summary.get("corner_analyses", {})
    if corners:
        context_parts.append(f"\nCorner analysis summary:")
        for lap_num, corner_list in corners.items():
            for c in corner_list[:5]:  # First 5 corners
                seg = c.get("segment", {})
                context_parts.append(
                    f"- {seg.get('segment_id', 'Unknown')}: "
                    f"entry {c.get('entry_speed_kmh', 0):.1f} km/h, "
                    f"apex {c.get('apex', {}).get('min_speed_kmh', 0):.1f} km/h, "
                    f"exit {c.get('exit', {}).get('exit_speed_kmh', 0):.1f} km/h"
                )

    # Dynamics summary
    dynamics = session_summary.get("dynamics_analyses", {})
    if dynamics:
        for lap_num, dyn in dynamics.items():
            gg = dyn.get("gg_metrics", {})
            context_parts.append(
                f"\nDynamics (Lap {lap_num}): "
                f"Peak lateral G: {gg.get('max_lateral_g', 0):.2f}, "
                f"Peak braking G: {gg.get('max_braking_g', 0):.2f}, "
                f"Friction utilization: {gg.get('friction_circle_utilization_pct', 0):.1f}%"
            )
            break  # Just first lap

    return "\n".join(context_parts)


class ChatService:
    """Handles chat conversations with racing coach LLM."""

    def __init__(self):
        load_dotenv()
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.client = None
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            logger.warning("GEMINI_API_KEY not set. Chat service will be unavailable.")

    def is_available(self) -> bool:
        """Check if chat service is available."""
        return self.client is not None

    def chat(
        self,
        message: str,
        session_summary: dict | None = None,
        conversation_history: list[dict] | None = None,
    ) -> str:
        """
        Send a chat message and get a response.

        Args:
            message: User's message
            session_summary: Session data for context (optional)
            conversation_history: Previous messages [{role, content}, ...]

        Returns:
            Assistant's response text
        """
        if not self.client:
            return "Chat service unavailable. Please set GEMINI_API_KEY environment variable."

        try:
            # Build context from session data
            context = ""
            if session_summary:
                context = _build_session_context(session_summary)

            # Build conversation contents
            contents = []

            # Add session context as first user message if available
            if context:
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(text=f"Here is my session data:\n\n{context}")]
                ))
                contents.append(types.Content(
                    role="model",
                    parts=[types.Part(text="I've reviewed your session data. I can see your lap times, corner analyses, and the key areas for improvement. What would you like to know about your driving?")]
                ))

            # Add conversation history
            if conversation_history:
                for msg in conversation_history:
                    role = "model" if msg.get("role") == "assistant" else "user"
                    contents.append(types.Content(
                        role=role,
                        parts=[types.Part(text=msg.get("content", ""))]
                    ))

            # Add current message
            contents.append(types.Content(
                role="user",
                parts=[types.Part(text=message)]
            ))

            # Generate response
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=COACHING_SYSTEM_PROMPT,
                    temperature=0.3,
                ),
            )

            return response.text

        except Exception as e:
            logger.error(f"Chat error: {e}")
            return f"Sorry, I encountered an error: {str(e)}"

    def chat_stream(
        self,
        message: str,
        session_summary: dict | None = None,
        conversation_history: list[dict] | None = None,
    ) -> Generator[str, None, None]:
        """
        Stream chat response for real-time display.

        Yields chunks of the response as they arrive.
        """
        if not self.client:
            yield "Chat service unavailable. Please set GEMINI_API_KEY environment variable."
            return

        try:
            # Build context from session data
            context = ""
            if session_summary:
                context = _build_session_context(session_summary)

            # Build conversation contents
            contents = []

            if context:
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(text=f"Here is my session data:\n\n{context}")]
                ))
                contents.append(types.Content(
                    role="model",
                    parts=[types.Part(text="I've reviewed your session data. What would you like to know?")]
                ))

            if conversation_history:
                for msg in conversation_history:
                    role = "model" if msg.get("role") == "assistant" else "user"
                    contents.append(types.Content(
                        role=role,
                        parts=[types.Part(text=msg.get("content", ""))]
                    ))

            contents.append(types.Content(
                role="user",
                parts=[types.Part(text=message)]
            ))

            # Stream response
            response = self.client.models.generate_content_stream(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=COACHING_SYSTEM_PROMPT,
                    temperature=0.3,
                ),
            )

            for chunk in response:
                if chunk.text:
                    yield chunk.text

        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield f"Sorry, I encountered an error: {str(e)}"


# Global instance
_chat_service: ChatService | None = None


def get_chat_service() -> ChatService:
    """Get or create the global chat service instance."""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
