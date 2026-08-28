import json
from pathlib import Path
from typing import List, Dict, Any


class AnswerEvaluator:
    def __init__(self, gold_dataset_path: Path):
        self.gold_dataset_path = gold_dataset_path
        self._load_gold_dataset()

    def _load_gold_dataset(self):
        self.gold_data = []
        if self.gold_dataset_path.exists():
            with open(self.gold_dataset_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        self.gold_data.append(json.loads(line))
        else:
            print(f"Warning: Gold dataset not found at {self.gold_dataset_path}")

    def evaluate(self, generated_responses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluates the generated responses against the gold dataset.
        Metrics: status accuracy, citation validity, etc.
        """
        if not self.gold_data or not generated_responses:
            return {"status": "NO_DATA", "metrics": {}}

        total = len(self.gold_data)
        status_match_count = 0
        valid_citation_count = 0
        generation_failures = 0

        # Create a lookup for quick evaluation
        response_lookup = {r.get("request_id"): r for r in generated_responses}

        for gold in self.gold_data:
            question_id = gold["question_id"]
            response = response_lookup.get(question_id)

            if not response:
                continue

            # 1. Status Accuracy
            if response.get("status") == gold["expected_status"]:
                status_match_count += 1

            if response.get("status") == "GENERATION_FAILED":
                generation_failures += 1

            # 2. Citation Validity
            if response.get("status") == "ANSWER" and gold["expected_status"] == "ANSWER":
                gold_citations = gold.get("gold_citations", [])
                response_citations = response.get("citations", [])

                # Simplified valid citation check: Are all response citations within allowed manual IDs?
                allowed_manual_ids = gold.get("allowed_manual_ids", [])
                valid = True
                for citation in response_citations:
                    evidence_id = citation.get("evidence_id", "")
                    manual_id = evidence_id.split(":")[0] if ":" in evidence_id else ""
                    if manual_id not in allowed_manual_ids:
                        valid = False
                        break

                if valid and response_citations:
                    valid_citation_count += 1

        metrics = {
            "total_evaluated": total,
            "status_accuracy": status_match_count / total if total > 0 else 0,
            "valid_citation_rate": valid_citation_count / total if total > 0 else 0,
            "generation_failure_rate": generation_failures / total if total > 0 else 0
        }

        return {
            "status": "EVALUATION_COMPLETED",
            "metrics": metrics
        }
