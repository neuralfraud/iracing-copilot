"""LLM-powered diagnosis: driver complaint + telemetry features + current car
setup -> a structured recommendation (what to try changing, and why).

Uses Claude (Anthropic Messages API) with Pydantic structured outputs, so the
result is a validated object - never free text to parse. This is "heuristic
reasoning only" (see iracing_copilot.features docstring): there is no
reference-lap comparison backing these recommendations, only the cited
telemetry evidence and general chassis-tuning knowledge in the system
prompt - treat `confidence` as the model's own hedge, not a guarantee.
"""

import json
from typing import List, Optional

import anthropic
from pydantic import BaseModel, Field

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000


class CitedEvidence(BaseModel):
    """One piece of telemetry evidence the diagnosis is actually based on."""

    source: str = Field(
        description="Where this came from, e.g. 'corner at 42% lap distance' or 'tire temps'"
    )
    observation: str = Field(
        description="The concrete signal observed, e.g. 'steering angle grew from "
        "0.1 to 0.5 rad while yaw rate stayed flat'"
    )


class SetupRecommendation(BaseModel):
    """One suggested change, addressed by the exact key path as it appears in
    the car's CarSetup dict - the setup schema differs by car, so there is no
    fixed set of component names."""

    setup_path: List[str] = Field(
        description="Nested key path into the CarSetup dict, e.g. "
        "['LeftFrontCorner', 'ArbSetting']"
    )
    current_value: Optional[str] = Field(
        default=None, description="The current value at that path, as a string, if known"
    )
    recommended_value: str = Field(
        description="The new value to try, as a string (e.g. '3 clicks', '+1.50 deg') - "
        "same format/units as current_value"
    )
    reasoning: str = Field(description="Why this change addresses the cited evidence")
    confidence: str = Field(description="One of: low, medium, high")


class Diagnosis(BaseModel):
    symptom_summary: str = Field(
        description="Plain restatement of what the driver is feeling, grounded in the evidence"
    )
    cited_evidence: List[CitedEvidence]
    recommendations: List[SetupRecommendation]
    caveats: List[str] = Field(
        description="Things that could also explain the symptom besides setup (driver "
        "technique, track evolution, tire wear, etc.), or missing data that limits confidence"
    )


SYSTEM_PROMPT = """You are a sim-racing race engineer giving setup advice for iRacing.

You will be given:
- a driver's spoken complaint about how the car feels,
- a feature summary extracted from that lap's telemetry (corner-by-corner
  speed/brake/steering/yaw data and under/oversteer "tells", tire
  temperatures) - these are heuristic signals, not ground truth,
- the car's current setup as a nested dict, exactly as iRacing's SDK exposes it.

Ground every recommendation in the cited evidence - don't invent causes the
telemetry doesn't support. If the complaint and telemetry don't clearly point
to a specific change, say so in `caveats` rather than guessing a number.

Known cause -> effect relationships to reason with (not an exhaustive list -
use general chassis-tuning knowledge too):
- Stiffer front ARB / softer rear ARB -> more rotation / less front grip (can
  induce oversteer); the reverse increases understeer resistance.
- Softer springs/dampers on an axle -> more grip and more roll on that axle.
- More rear wedge (cross-weight) -> more rear grip on corner entry, can
  increase oversteer on exit if overdone.
- More negative camber -> more grip at higher slip angles, can reduce
  straight-line grip and increase inner-edge tire wear/temp.
- More rear brake bias -> easier rear lock-up/rotation under braking; more
  front bias -> more stable braking but can increase front lock-up/understeer
  on entry.
- Softer/lower tire pressure on an axle -> more mechanical grip there but
  more heat buildup; same logic applies front vs. rear.

Address every recommendation by the exact `setup_path` as it appears in the
provided CarSetup dict - never invent a key that isn't present there. Keep
`recommended_value` in the same format/units you see in `current_value` (e.g.
if the setup shows "3 clicks", recommend "2 clicks", not a raw number).

If you don't have enough evidence to recommend any change, return an empty
`recommendations` list and explain why in `caveats` - don't force a guess.
"""


class DiagnosisError(RuntimeError):
    """Raised when the Claude API call for a diagnosis fails."""


def diagnose(complaint, lap_features, car_setup, client=None, model=MODEL):
    """Run one diagnosis call.

    complaint: str - transcribed driver feedback
    lap_features: dict - LapFeatures.to_dict() from iracing_copilot.features
    car_setup: dict - CarSetupReader.read()/poll_for_update() output
    client: an anthropic.Anthropic instance (created from env/ant-cli auth if not passed)

    Returns a validated Diagnosis. Raises DiagnosisError on any API failure.
    """
    client = client or anthropic.Anthropic()

    user_content = (
        f"Driver complaint: {complaint}\n\n"
        f"Telemetry feature summary (JSON):\n{_to_json(lap_features)}\n\n"
        f"Current car setup (JSON):\n{_to_json(car_setup)}"
    )

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            output_format=Diagnosis,
            # claude-opus-5-5 defaults to "medium" effort (claude-opus-5 defaulted to
            # "high"); pin "high" explicitly to keep this intelligence-sensitive
            # diagnosis at the same reasoning depth as before the migration.
            output_config={"effort": "high"},
        )
    except anthropic.AuthenticationError as e:
        raise DiagnosisError(f"invalid Anthropic API credentials: {e}") from e
    except anthropic.RateLimitError as e:
        raise DiagnosisError(f"rate limited by Anthropic API: {e}") from e
    except anthropic.APIConnectionError as e:
        raise DiagnosisError(f"could not reach Anthropic API: {e}") from e
    except anthropic.APIStatusError as e:
        raise DiagnosisError(f"Anthropic API error ({e.status_code}): {e.message}") from e

    return response.parsed_output


def _to_json(data):
    return json.dumps(data, indent=2, sort_keys=True, default=str)
