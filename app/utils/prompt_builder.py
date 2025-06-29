import json
from pathlib import Path


class PromptBuilder:
    """Class for building prompts with different strategies"""
    
    def __init__(self):
        self.few_shot_templates = self._load_few_shot_templates()
    
    def _load_few_shot_templates(self):
        """Load few-shot templates from JSON file"""
        template_path = Path(__file__).parent / "few_shot_templates.json"
        try:
            with open(template_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading few-shot templates: {e}")
            return []
    
    def build_prompt(self, strategy, user_input):
        """Build prompt based on strategy"""
        if strategy == 'few_shot':
            sections = [
                f"Description:\n{example['description']}\n\nBPMN:\n{example['bpmn']}\n"
                for example in self.few_shot_templates
                if 'description' in example and 'bpmn' in example
            ]
            sections.append(f"Description:\n{user_input}\n\nBPMN:\n")
            return "\n".join(sections)
        
        elif strategy == 'zero_shot':
            return f"Please generate a BPMN model for the following description:\n\n{user_input}\n\nBPMN:"
        
        else:
            raise ValueError(f"Unsupported prompting strategy: {strategy}")
