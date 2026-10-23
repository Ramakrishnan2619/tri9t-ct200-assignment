import os
import re
import json
import hashlib
import httpx
from typing import Optional
from app.schemas import LLMOutputSchema, TestCase

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock").lower()
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-1.5-flash")

def build_qa_prompt(context_text: str) -> str:
    """
    Constructs a domain-specific prompt for generating IEC 62304 compliant QA test cases.
    """
    return f"""You are a Lead Medical Device Software QA Engineer specializing in IEC 62304 software verification.
Your task is to generate 3 to 5 rigorous Quality Assurance (QA) test case ideas based strictly on the provided technical specification text for the CardioTrack CT-200 Blood Pressure Monitor.

REQUIREMENTS:
1. Every test case must be concrete, actionable, and repeatable by a third-party QA tester.
2. Cover nominal operation, boundary thresholds, error fault injection, and safety-critical failure modes where applicable.
3. Return ONLY a valid JSON object matching the exact schema below, with no markdown code fences, no explanations, and no surrounding commentary.

JSON SCHEMA:
{{
  "test_cases": [
    {{
      "test_title": "string: concise, imperative action title",
      "prerequisites": "string: initial device state, battery level, cuff attachment",
      "steps": [
        "Step 1: detail exact user or test fixture action",
        "Step 2: detail subsequent action"
      ],
      "expected_result": "string: exact verifiable outcome (e.g. display codes, deflation timing, threshold response)"
    }}
  ]
}}

TECHNICAL SPECIFICATION CONTEXT:
\"\"\"
{context_text}
\"\"\"
"""

def extract_and_parse_json(raw_text: str) -> dict:
    """
    Resilient JSON extractor that strips markdown fences, conversational prefixes,
    and trailing garbage.
    """
    text = raw_text.strip()
    # Strip markdown code blocks
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    text = text.strip()

    # Find outermost JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)

    return json.loads(text)

def generate_mock_test_cases(context_text: str) -> dict:
    """
    High-fidelity deterministic QA generator for CT-200.
    Provides realistic IEC 62304 test cases tailored to the provided context
    when running without external API keys.
    """
    lower = context_text.lower()
    cases = []

    if "overpressure" in lower or "299 mmhg" in lower or "deflation" in lower:
        cases.append({
            "test_title": "Verify Emergency Cuff Deflation on Pressure Exceeding 299 mmHg",
            "prerequisites": "CT-200 unit powered on; pneumatic pressure simulator connected to cuff port.",
            "steps": [
                "1. Initiate standard oscillometric measurement cycle.",
                "2. Using the pneumatic simulator, manually ramp cuff pressure to 302 mmHg.",
                "3. Observe high-speed pressure transducer and timer."
            ],
            "expected_result": "Independent safety valve triggers immediately; cuff vents to atmospheric pressure within 2.0 seconds and displays E3."
        })

    if "error codes" in lower or "e1" in lower or "e2" in lower or "e6" in lower:
        cases.append({
            "test_title": "Verify Motion Artifact Detection and E2 Error Prompt",
            "prerequisites": "Device powered on with standard 22-32 cm cuff positioned on test arm rig.",
            "steps": [
                "1. Begin inflation sequence.",
                "2. Apply 2 Hz simulated mechanical motion during deflation phase at 120 mmHg.",
                "3. Record LCD behavior and error annunciator."
            ],
            "expected_result": "Measurement aborts without calculating systolic/diastolic values; displays error code E2 with retry prompt."
        })

    if "battery" in lower or "alkaline" in lower or "capacity" in lower:
        cases.append({
            "test_title": "Verify Low-Battery Annunciation and Lockout Threshold",
            "prerequisites": "Programmable DC power supply connected to battery terminals in place of 4x AA cells.",
            "steps": [
                "1. Lower DC supply voltage to simulate remaining capacity below rated low threshold.",
                "2. Power on device and attempt to start measurement."
            ],
            "expected_result": "Low-battery warning icon flashes on LCD; if below critical threshold, measurement is inhibited."
        })

    if "bluetooth" in lower or "sync" in lower or "export" in lower:
        cases.append({
            "test_title": "Verify Bluetooth Low Energy Data Synchronization and Export Integrity",
            "prerequisites": "CT-200 paired with test mobile companion app; 10 readings stored in memory.",
            "steps": [
                "1. Launch companion application within 3 meters of active device.",
                "2. Initiate CSV data export of stored readings.",
                "3. Verify columns and record values."
            ],
            "expected_result": "All 10 stored records transfer accurately matching device memory with timestamp, profile, and classification."
        })

    # Default fallback test cases if general text
    if len(cases) < 3:
        cases.append({
            "test_title": "Verify Section Boundary Functional Response",
            "prerequisites": "Device powered with nominal DC supply at 25°C ambient temperature.",
            "steps": [
                "1. Execute operational sequence specified in section text.",
                "2. Monitor firmware state transitions and LCD display outputs.",
                "3. Validate against manufacturer specifications."
            ],
            "expected_result": "Device operates within specified performance criteria without software freeze or unhandled error state."
        })
        cases.append({
            "test_title": "Verify User Profile State Persistence Across Power Cycles",
            "prerequisites": "Device in standby state with valid battery installation.",
            "steps": [
                "1. Switch active profile using profile selector button.",
                "2. Power off device by pressing power button for 2 seconds.",
                "3. Power device back on and check active profile."
            ],
            "expected_result": "Previously selected profile remains active; prior stored historical records are intact."
        })

    return {"test_cases": cases[:5]}

def call_live_llm(prompt: str) -> str:
    """Calls the configured external LLM provider."""
    if not LLM_API_KEY:
        raise ValueError("LLM_API_KEY is not set.")

    if "gemini" in LLM_PROVIDER or "google" in LLM_PROVIDER:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{LLM_MODEL}:generateContent?key={LLM_API_KEY}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

    elif "groq" in LLM_PROVIDER:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": LLM_MODEL if "llama" in LLM_MODEL else "llama-3.1-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    elif "openai" in LLM_PROVIDER or "openrouter" in LLM_PROVIDER:
        base_url = "https://openrouter.ai/api/v1" if "openrouter" in LLM_PROVIDER else "https://api.openai.com/v1"
        url = f"{base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
            
    else:
        raise ValueError(f"Unsupported LLM provider: {LLM_PROVIDER}")

def generate_qa_test_cases(context_text: str, max_retries: int = 3) -> tuple[list[TestCase], str]:
    """
    Generates structured QA test cases with strict Pydantic validation,
    multi-attempt error feedback retry loop, and safety fallback.
    Returns (validated_test_cases, raw_prompt_used).
    """
    prompt = build_qa_prompt(context_text)

    # If mock mode or no API key, use domain-authentic generator
    if LLM_PROVIDER == "mock" or not LLM_API_KEY:
        mock_data = generate_mock_test_cases(context_text)
        validated = LLMOutputSchema(**mock_data)
        return validated.test_cases, prompt

    # Live LLM execution with self-correction retry loop
    current_prompt = prompt
    last_error = None

    for attempt in range(max_retries):
        try:
            raw_response = call_live_llm(current_prompt)
            parsed_json = extract_and_parse_json(raw_response)
            validated = LLMOutputSchema(**parsed_json)
            return validated.test_cases, prompt
        except Exception as err:
            last_error = str(err)
            print(f"[LLM Generation Attempt {attempt + 1}/{max_retries}] Validation failed: {err}")
            # Feed validation failure back to LLM context for self-correction
            current_prompt = (
                f"{prompt}\n\n"
                f"PREVIOUS ATTEMPT FAILED SCHEMA VALIDATION:\n"
                f"Error: {last_error}\n"
                f"Please fix the schema formatting and return ONLY compliant JSON matching the requested structure."
            )

    # Fallback to local medical QA generator if live provider repeatedly fails
    print(f"Notice: Live LLM retry limit reached ({last_error}). Triggering deterministic fallback generator.")
    fallback_data = generate_mock_test_cases(context_text)
    validated = LLMOutputSchema(**fallback_data)
    return validated.test_cases, prompt
