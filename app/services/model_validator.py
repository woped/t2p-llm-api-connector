import re


class ModelValidator:
    """Validate and sanitize generated BPMN-like JSON structures."""

    @staticmethod
    def _as_list(value):
        return value if isinstance(value, list) else []

    @staticmethod
    def _dedupe_by_id(items):
        seen = set()
        deduped = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            deduped.append(item)
        return deduped

    def sanitize_model(self, model):
        """Normalize shape, deduplicate IDs, and drop invalid flows."""
        model = model if isinstance(model, dict) else {}

        events = self._dedupe_by_id(self._as_list(model.get("events")))
        tasks = self._dedupe_by_id(self._as_list(model.get("tasks")))
        gateways = self._dedupe_by_id(self._as_list(model.get("gateways")))
        flows = self._dedupe_by_id(self._as_list(model.get("flows")))

        node_ids = {
            item.get("id") for item in events + tasks + gateways if item.get("id")
        }

        valid_flows = []
        for flow in flows:
            source = flow.get("source")
            target = flow.get("target")
            if source not in node_ids or target not in node_ids:
                continue
            flow["type"] = "sequenceFlow"
            valid_flows.append(flow)

        return {
            "events": events,
            "tasks": tasks,
            "gateways": gateways,
            "flows": valid_flows,
        }

    def validate_model(self, model, source_text=""):
        """Return a list of validation issues found in the model."""
        issues = []

        events = self._as_list(model.get("events"))
        tasks = self._as_list(model.get("tasks"))
        gateways = self._as_list(model.get("gateways"))
        flows = self._as_list(model.get("flows"))

        starts = [e for e in events if e.get("type") == "startEvent"]
        ends = [e for e in events if e.get("type") == "endEvent"]

        if len(starts) != 1:
            issues.append("Model must contain exactly one startEvent.")
        if len(ends) != 1:
            issues.append("Model must contain exactly one endEvent.")

        nodes = events + tasks + gateways
        node_ids = [n.get("id") for n in nodes if n.get("id")]
        node_id_set = set(node_ids)

        incoming = {node_id: 0 for node_id in node_id_set}
        outgoing = {node_id: 0 for node_id in node_id_set}

        for flow in flows:
            source = flow.get("source")
            target = flow.get("target")
            if source not in node_id_set or target not in node_id_set:
                issues.append(
                    f"Flow {flow.get('id')} references unknown node(s): {source} -> {target}."
                )
                continue
            outgoing[source] += 1
            incoming[target] += 1

        start_id = starts[0].get("id") if len(starts) == 1 else None
        end_id = ends[0].get("id") if len(ends) == 1 else None

        for node_id in node_id_set:
            if node_id != start_id and incoming[node_id] == 0:
                issues.append(f"Node {node_id} has no incoming sequence flow.")
            if node_id != end_id and outgoing[node_id] == 0:
                issues.append(f"Node {node_id} has no outgoing sequence flow.")

        for gateway in gateways:
            gateway_id = gateway.get("id")
            if not gateway_id:
                continue
            role = gateway.get("role")
            branch_count = gateway.get("branch_count")
            paired_gateway_id = gateway.get("paired_gateway_id")

            if incoming.get(gateway_id, 0) == 0:
                issues.append(f"Gateway {gateway_id} has no incoming flow.")
            if outgoing.get(gateway_id, 0) == 0:
                issues.append(f"Gateway {gateway_id} has no outgoing flow.")
            if (
                gateway.get("type") == "exclusiveGateway"
                and incoming.get(gateway_id, 0) == 1
                and outgoing.get(gateway_id, 0) == 1
            ):
                issues.append(
                    f"Exclusive gateway {gateway_id} has no effective branching (1 in, 1 out)."
                )

            if role == "split" and outgoing.get(gateway_id, 0) < 2:
                issues.append(
                    f"Gateway {gateway_id} is marked as split but has fewer than 2 outgoing flows."
                )
            if role == "join" and incoming.get(gateway_id, 0) < 2:
                issues.append(
                    f"Gateway {gateway_id} is marked as join but has fewer than 2 incoming flows."
                )

            if isinstance(branch_count, int) and branch_count >= 2:
                outgoing_count = outgoing.get(gateway_id, 0)
                incoming_count = incoming.get(gateway_id, 0)
                if role == "split" and outgoing_count != branch_count:
                    issues.append(
                        f"Gateway {gateway_id} split branch_count={branch_count} "
                        f"but outgoing flow count is {outgoing_count}."
                    )
                if role == "join" and incoming_count != branch_count:
                    issues.append(
                        f"Gateway {gateway_id} join branch_count={branch_count} "
                        f"but incoming flow count is {incoming_count}."
                    )

            if paired_gateway_id and paired_gateway_id not in node_id_set:
                issues.append(
                    f"Gateway {gateway_id} references missing paired gateway {paired_gateway_id}."
                )

            branch_cues = gateway.get("branch_cues")
            if role == "split" and isinstance(branch_cues, list) and len(branch_cues) >= 2:
                outgoing_count = outgoing.get(gateway_id, 0)
                if outgoing_count < len(branch_cues):
                    issues.append(
                        f"Gateway {gateway_id} declares {len(branch_cues)} branch cues "
                        f"but has only {outgoing_count} outgoing flows."
                    )

        text = (source_text or "").lower()
        has_condition_words = bool(
            re.search(r"\b(if|otherwise|whether|either|or)\b", text)
        )
        strong_loop_words = bool(
            re.search(
                r"\b(until|again|retest(?:ed|s|ing)?|retry(?:ing)?|loop(?:ing)?|repeat(?:ed|s|ing)?)\b",
                text,
            )
        )
        explicit_rework_phrase = bool(
            re.search(r"\b(return(?:s|ed|ing)?\s+(for|to)\s+(correction|rework|repair|retest))\b", text)
        )
        has_loop_words = strong_loop_words or explicit_rework_phrase

        gateway_outgoing_counts = [outgoing.get(g.get("id"), 0) for g in gateways]
        has_real_split = any(count >= 2 for count in gateway_outgoing_counts)
        if has_condition_words and not has_real_split:
            issues.append(
                "Conditional language found in text but no gateway with multiple outgoing branches."
            )

        if has_loop_words and not self._has_back_edge(model):
            issues.append(
                "Loop/retest language found in text but no backward/loop flow detected."
            )

        if has_loop_words:
            split_gateways = [g for g in gateways if g.get("role") == "split"]
            has_loop_split = any(
                isinstance(g.get("branch_cues"), list)
                and any(
                    isinstance(cue, str)
                    and re.search(r"\b(remains|retry|retest|again|return|repeat|fail)\b", cue.lower())
                    for cue in g.get("branch_cues", [])
                )
                for g in split_gateways
            )
            if not has_loop_split:
                issues.append(
                    "Loop language found in text but no split gateway encodes loop branch cues."
                )

        return issues

    def _has_back_edge(self, model):
        events = self._as_list(model.get("events"))
        tasks = self._as_list(model.get("tasks"))
        gateways = self._as_list(model.get("gateways"))
        flows = self._as_list(model.get("flows"))

        ordered_ids = [
            item.get("id")
            for item in events + tasks + gateways
            if isinstance(item, dict) and item.get("id")
        ]
        position = {node_id: idx for idx, node_id in enumerate(ordered_ids)}

        for flow in flows:
            source = flow.get("source")
            target = flow.get("target")
            if source in position and target in position and position[target] <= position[source]:
                return True
        return False
