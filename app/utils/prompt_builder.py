import logging
from pathlib import Path

logger = logging.getLogger(__name__)

STRICT_JSON_REMINDER = (
    "STRICT JSON REMINDER: return exactly one valid JSON object only. "
    "Do not use markdown fences, code blocks, explanations, or extra text."
)


class PromptBuilder:
    """Class for building prompts with different strategies"""

    _FEW_SHOT_PACK_FILES = [
        "00_shared_rules.txt",
        "01_start_event_prompt.txt",
        "02_tasks_prompt.txt",
        "03_gateways_prompt.txt",
        "04_flows_prompt.txt",
        "05_end_event_prompt.txt",
        "06_merge_and_validate_prompt.txt",
    ]
    _ZERO_SHOT_PROMPT_FILE = "00_zero_shot_prompt.txt"

    def __init__(self):
        self.few_shot_prompt_pack = self._load_few_shot_prompt_pack()
        self.zero_shot_prompt_template = self._load_zero_shot_prompt_template()

    def _load_few_shot_prompt_pack(self):
        """Load the stepwise few-shot prompt pack from text files."""
        prompt_dir = Path(__file__).parent / "few-shot-prompts"
        pack = {}
        for file_name in self._FEW_SHOT_PACK_FILES:
            file_path = prompt_dir / file_name
            try:
                pack[file_name] = file_path.read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.warning("Error loading prompt pack file %s: %s", file_name, e)
                pack[file_name] = ""
        return pack

    def _load_zero_shot_prompt_template(self):
        """Load the zero-shot prompt template from text file."""
        file_path = (
            Path(__file__).parent
            / "zero-shot-prompts"
            / self._ZERO_SHOT_PROMPT_FILE
        )
        try:
            return file_path.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning("Error loading zero-shot prompt template %s: %s", file_path, e)
            return ""

    def _build_zero_shot_prompt(self, user_input):
        """Build zero-shot prompt using external template with fallback."""
        if self.zero_shot_prompt_template:
            return self.zero_shot_prompt_template.replace("{{PROCESS_TEXT}}", user_input)
        return (
            "Please generate a BPMN model for the following description:\n\n"
            f"{user_input}\n\nBPMN:"
        )

    def _build_stepwise_few_shot_prompt(self, user_input):
        """Compose one prompt that applies the stepwise extraction method internally."""
        shared_rules = self.few_shot_prompt_pack.get("00_shared_rules.txt", "")
        start_prompt = self.few_shot_prompt_pack.get("01_start_event_prompt.txt", "")
        tasks_prompt = self.few_shot_prompt_pack.get("02_tasks_prompt.txt", "")
        gateways_prompt = self.few_shot_prompt_pack.get("03_gateways_prompt.txt", "")
        flows_prompt = self.few_shot_prompt_pack.get("04_flows_prompt.txt", "")
        end_prompt = self.few_shot_prompt_pack.get("05_end_event_prompt.txt", "")
        merge_prompt = self.few_shot_prompt_pack.get(
            "06_merge_and_validate_prompt.txt", ""
        )

        if not any(
            [
                shared_rules,
                start_prompt,
                tasks_prompt,
                gateways_prompt,
                flows_prompt,
                end_prompt,
                merge_prompt,
            ]
        ):
            logger.warning(
                "Few-shot prompt pack is unavailable; falling back to zero-shot prompt."
            )
            return self._build_zero_shot_prompt(user_input)

        sections = [
            "Use the following stepwise few-shot method internally. "
            "Do not return intermediate steps. Return only the final merged JSON object.",
            "",
            "=== SHARED RULES ===",
            shared_rules,
            "",
            "=== STEP 1: START EVENT ===",
            start_prompt.replace("{{PROCESS_TEXT}}", user_input),
            "",
            "=== STEP 2: TASKS ===",
            tasks_prompt.replace("{{PROCESS_TEXT}}", user_input),
            "",
            "=== STEP 3: GATEWAYS ===",
            gateways_prompt.replace("{{PROCESS_TEXT}}", user_input),
            "",
            "=== STEP 4: END EVENT ===",
            end_prompt.replace("{{PROCESS_TEXT}}", user_input),
            "",
            "=== STEP 5: FLOWS ===",
            flows_prompt.replace("{{PROCESS_TEXT}}", user_input).replace(
                "{{KNOWN_ELEMENTS_JSON}}",
                "Use elements extracted in steps 1-4 as known elements.",
            ),
            "",
            "=== STEP 6: MERGE + VALIDATE ===",
            merge_prompt.replace(
                "{{PARTIAL_OUTPUTS_JSON}}",
                "Use your outputs from steps 1-5 as partial outputs.",
            ),
            "",
            STRICT_JSON_REMINDER,
            "",
            "PROCESS TEXT:",
            user_input,
            "",
            "Return only the final JSON object.",
        ]
        return "\n".join([s for s in sections if s is not None])

    def build_prompt(self, strategy, user_input):
        """Build prompt based on strategy"""
        if strategy == "few_shot":
            return self._build_stepwise_few_shot_prompt(user_input)

        elif strategy == "zero_shot":
            return self._build_zero_shot_prompt(user_input)

        else:
            raise ValueError(f"Unsupported prompting strategy: {strategy}")
