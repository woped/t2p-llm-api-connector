import logging
import time
import json
from openai import OpenAI
import google.generativeai as genai
from app.utils.prompt_builder import PromptBuilder
from app.services import model_registry
from app.services.model_validator import ModelValidator


logger = logging.getLogger(__name__)


class LLMService:
    """Service class for handling LLM API calls"""

    def __init__(self):
        self.prompt_builder = PromptBuilder()
        self.model_validator = ModelValidator()

    @staticmethod
    def _extract_json_object(text):
        """Extract and parse a JSON object from model output text."""
        content = (text or "").strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Model output does not contain a JSON object.")
        return json.loads(content[start : end + 1])

    @staticmethod
    def _merge_known_elements(partials):
        """Merge step outputs into known elements map by preserving first-seen IDs."""
        merged = {"events": [], "tasks": [], "gateways": []}
        seen = {"events": set(), "tasks": set(), "gateways": set()}

        for part in partials:
            if not isinstance(part, dict):
                continue
            for key in ("events", "tasks", "gateways"):
                for item in part.get(key, []):
                    if not isinstance(item, dict):
                        continue
                    item_id = item.get("id")
                    if not item_id or item_id in seen[key]:
                        continue
                    seen[key].add(item_id)
                    merged[key].append(item)
        return merged

    def _build_repair_prompt(self, user_text, model_json, issues):
        """Create a repair prompt from validation findings."""
        issues_block = "\n".join(f"- {issue}" for issue in issues)
        model_block = json.dumps(model_json, ensure_ascii=False, indent=2)
        return (
            "You are repairing a BPMN JSON model to satisfy strict structural rules.\n"
            "Return JSON only. Preserve IDs where possible, but fix broken structure.\n\n"
            "Process text:\n"
            f"{user_text}\n\n"
            "Validation issues to fix:\n"
            f"{issues_block}\n\n"
            "Current model:\n"
            f"{model_block}\n"
        )

    def _run_few_shot_orchestration(self, user_text, generate_once):
        """Run real multi-call few-shot extraction and merge with validation."""
        pack = self.prompt_builder.few_shot_prompt_pack
        shared = pack.get("00_shared_rules.txt", "")

        required_files = [
            "01_start_event_prompt.txt",
            "02_tasks_prompt.txt",
            "03_gateways_prompt.txt",
            "04_flows_prompt.txt",
            "05_end_event_prompt.txt",
            "06_merge_and_validate_prompt.txt",
        ]
        for file_name in required_files:
            if not pack.get(file_name):
                raise ValueError(f"Missing few-shot prompt file: {file_name}")

        def compose_prompt(step_text, known_elements=None, partial_outputs=None):
            body = step_text.replace("{{PROCESS_TEXT}}", user_text)
            if "{{KNOWN_ELEMENTS_JSON}}" in body:
                body = body.replace(
                    "{{KNOWN_ELEMENTS_JSON}}",
                    json.dumps(known_elements or {}, ensure_ascii=False, indent=2),
                )
            if "{{PARTIAL_OUTPUTS_JSON}}" in body:
                body = body.replace(
                    "{{PARTIAL_OUTPUTS_JSON}}",
                    json.dumps(partial_outputs or {}, ensure_ascii=False, indent=2),
                )
            return (
                f"{shared}\n\n{body}\n\n"
                "Return only JSON matching the step schema."
            ).strip()

        def run_json_step(step_name, prompt):
            response_text = generate_once(prompt)
            try:
                return self._extract_json_object(response_text)
            except ValueError as first_error:
                logger.warning(
                    "few-shot step '%s' returned non-JSON output; retrying with strict JSON reminder",
                    step_name,
                )
                retry_prompt = (
                    f"{prompt}\n\n"
                    "IMPORTANT: Your previous answer was not valid JSON. "
                    "Respond again with exactly one JSON object matching the requested schema. "
                    "No markdown fences, no explanations, no extra text."
                )
                retry_response_text = generate_once(retry_prompt)
                try:
                    return self._extract_json_object(retry_response_text)
                except ValueError:
                    raise ValueError(
                        f"Few-shot step '{step_name}' did not return a JSON object after retry."
                    ) from first_error

        partials = {}

        try:
            start_obj = run_json_step(
                "start_event", compose_prompt(pack["01_start_event_prompt.txt"])
            )
        except ValueError as start_error:
            logger.warning(
                "few-shot start_event step failed (%s); falling back to default start event",
                start_error,
            )
            start_obj = {
                "events": [
                    {
                        "id": "startEvent1",
                        "type": "startEvent",
                        "name": "Start",
                    }
                ]
            }
        partials["start"] = start_obj

        try:
            tasks_obj = run_json_step(
                "tasks", compose_prompt(pack["02_tasks_prompt.txt"])
            )
        except ValueError as tasks_error:
            logger.warning(
                "few-shot tasks step failed (%s); falling back to empty tasks list",
                tasks_error,
            )
            tasks_obj = {"tasks": []}
        partials["tasks"] = tasks_obj

        try:
            gateways_obj = run_json_step(
                "gateways", compose_prompt(pack["03_gateways_prompt.txt"])
            )
        except ValueError as gateways_error:
            logger.warning(
                "few-shot gateways step failed (%s); falling back to empty gateways list",
                gateways_error,
            )
            gateways_obj = {"gateways": []}
        partials["gateways"] = gateways_obj

        try:
            end_obj = run_json_step(
                "end_event", compose_prompt(pack["05_end_event_prompt.txt"])
            )
        except ValueError as end_error:
            logger.warning(
                "few-shot end_event step failed (%s); falling back to default end event",
                end_error,
            )
            end_obj = {
                "events": [
                    {
                        "id": "endEvent1",
                        "type": "endEvent",
                        "name": "End",
                    }
                ]
            }
        partials["end"] = end_obj

        known_elements = self._merge_known_elements(
            [start_obj, tasks_obj, gateways_obj, end_obj]
        )
        try:
            flows_obj = run_json_step(
                "flows",
                compose_prompt(
                    pack["04_flows_prompt.txt"], known_elements=known_elements
                ),
            )
        except ValueError as flows_error:
            logger.warning(
                "few-shot flows step failed (%s); falling back to empty flows list",
                flows_error,
            )
            flows_obj = {"flows": []}
        partials["flows"] = flows_obj

        merge_input = {
            "events": known_elements.get("events", []),
            "tasks": known_elements.get("tasks", []),
            "gateways": known_elements.get("gateways", []),
            "flows": flows_obj.get("flows", []),
            "partials": partials,
        }
        try:
            merged_obj = run_json_step(
                "merge_and_validate",
                compose_prompt(
                    pack["06_merge_and_validate_prompt.txt"],
                    partial_outputs=merge_input,
                ),
            )
        except ValueError as merge_error:
            logger.warning(
                "few-shot merge step failed (%s); falling back to deterministic local merge",
                merge_error,
            )
            merged_obj = {
                "events": list(known_elements.get("events", [])),
                "tasks": list(known_elements.get("tasks", [])),
                "gateways": list(known_elements.get("gateways", [])),
                "flows": list(flows_obj.get("flows", [])),
            }

        sanitized = self.model_validator.sanitize_model(merged_obj)
        issues = self.model_validator.validate_model(sanitized, user_text)

        if issues:
            logger.warning(
                "few-shot validation found %d issue(s), running repair pass",
                len(issues),
            )
            repair_prompt = self._build_repair_prompt(user_text, sanitized, issues)
            try:
                repaired_obj = run_json_step("repair", repair_prompt)
                sanitized = self.model_validator.sanitize_model(repaired_obj)
                remaining_issues = self.model_validator.validate_model(sanitized, user_text)
                if remaining_issues:
                    raise ValueError(
                        "Few-shot repair produced invalid model: "
                        + "; ".join(remaining_issues)
                    )
            except ValueError as repair_error:
                logger.warning(
                    "few-shot repair step failed (%s); returning pre-repair sanitized model",
                    repair_error,
                )

        return json.dumps(sanitized, ensure_ascii=False)

    @staticmethod
    def _openai_generate_once(client, system_prompt, model, prompt):
        model_name = (model or "").lower()
        request_kwargs = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "model": model,
            "max_completion_tokens": 4096,
        }
        # GPT-5 variants can reject explicit temperature values and only accept
        # provider defaults. Avoid first-attempt 400s by omitting it up front.
        if not model_name.startswith("gpt-5"):
            request_kwargs["temperature"] = 0
        try:
            chat_completion = client.chat.completions.create(**request_kwargs)
        except Exception as e:
            # Some OpenAI models (for example GPT-5 variants) only accept the
            # default temperature and reject an explicit value.
            error_text = str(e).lower()
            if "temperature" in error_text and "unsupported" in error_text:
                logger.info(
                    "Retrying OpenAI call without explicit temperature (model=%s)",
                    model,
                )
                request_kwargs.pop("temperature", None)
                chat_completion = client.chat.completions.create(**request_kwargs)
            else:
                raise
        return (chat_completion.choices[0].message.content or "").strip()

    @staticmethod
    def _gemini_generate_once(gen_model, prompt):
        response = gen_model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.0, top_k=1, top_p=1.0, max_output_tokens=2048
            ),
        )
        return ((response.text or "") if hasattr(response, "text") else "").strip()

    def call_openai(
        self, api_key, system_prompt, user_text, prompting_strategy, model="gpt-4o"
    ):
        """Call OpenAI GPT model.

        ``model`` defaults to ``gpt-4o`` so existing (v1) callers and tests keep
        working; the v2 ``/generate`` flow passes the model selected from the
        registry.
        """
        if not user_text:
            logger.warning("call_openai: empty user_text provided")
        start_time = time.time()
        prompt = self.prompt_builder.build_prompt(prompting_strategy, user_text)
        logger.debug(
            "call_openai: strategy=%s, model=%s, user_text_len=%d, prompt_len=%d",
            prompting_strategy,
            model,
            len(user_text or ""),
            len(prompt or ""),
        )
        client = OpenAI(api_key=api_key)

        try:
            if prompting_strategy == "few_shot":
                try:
                    logger.info("Running OpenAI few-shot multi-call orchestration")
                    return self._run_few_shot_orchestration(
                        user_text,
                        lambda prompt: self._openai_generate_once(
                            client, system_prompt, model, prompt
                        ),
                    )
                except Exception as orchestration_error:
                    logger.warning("Few-shot orchestration failed: %s", orchestration_error)
                    raise

            logger.info("Calling OpenAI chat.completions (model=%s)", model)
            content = self._openai_generate_once(client, system_prompt, model, prompt)
            duration = time.time() - start_time
            logger.info(
                "OpenAI response received in %.3fs (len=%d)",
                duration,
                len(content),
            )
            return content.strip()
        except Exception as e:
            logger.exception("OpenAI call failed: %s", e)
            raise

    def call_gemini(
        self,
        api_key,
        system_prompt,
        user_text,
        prompting_strategy,
        model="gemini-1.5-pro",
    ):
        """Call Google Gemini model.

        ``model`` defaults to ``gemini-1.5-pro`` for backward compatibility; the
        v2 ``/generate`` flow passes the model selected from the registry.
        """
        if not user_text:
            logger.warning("call_gemini: empty user_text provided")
        start_time = time.time()
        prompt = self.prompt_builder.build_prompt(prompting_strategy, user_text)
        logger.debug(
            "call_gemini: strategy=%s, model=%s, user_text_len=%d, prompt_len=%d",
            prompting_strategy,
            model,
            len(user_text or ""),
            len(prompt or ""),
        )

        genai.configure(api_key=api_key)

        gen_model = genai.GenerativeModel(
            model_name=model, system_instruction=system_prompt
        )

        try:
            if prompting_strategy == "few_shot":
                try:
                    logger.info("Running Gemini few-shot multi-call orchestration")
                    return self._run_few_shot_orchestration(
                        user_text,
                        lambda step_prompt: self._gemini_generate_once(
                            gen_model, step_prompt
                        ),
                    )
                except Exception as orchestration_error:
                    logger.warning("Few-shot orchestration failed: %s", orchestration_error)
                    raise

            logger.info("Calling Gemini generate_content (model=%s)", model)
            text = self._gemini_generate_once(gen_model, prompt)
            duration = time.time() - start_time
            logger.info(
                "Gemini response received in %.3fs (len=%d)",
                duration,
                len(text),
            )
            return text.strip()
        except Exception as e:
            logger.exception("Gemini call failed: %s", e)
            raise

    def generate(self, api_key, provider, model, user_text, system_prompt,
                 prompting_strategy="zero_shot"):
        """Provider-agnostic entry point used by the v2 ``/generate`` route.

        Looks up the dispatch method for ``provider`` in the registry and calls
        it with the registry-selected ``model``. Raises ``ValueError`` if the
        provider has no dispatch mapping (the route validates the pair against
        the registry first, so this is a defensive guard).
        """
        method_name = model_registry.dispatch_method(provider)
        if method_name is None:
            raise ValueError(f"Unsupported provider: {provider}")
        method = getattr(self, method_name)
        return method(
            api_key=api_key,
            system_prompt=system_prompt,
            user_text=user_text,
            prompting_strategy=prompting_strategy,
            model=model,
        )
