"""Check workflow YAML and syntax of embedded Bash scripts."""
from pathlib import Path
import re
import subprocess
import sys
import yaml


def main():
    for path in Path('.github/workflows').glob('*.yml'):
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        for job in data.get('jobs', {}).values():
            for step in job.get('steps', []):
                script = step.get('run')
                if not script:
                    continue
                # Inputs and output values must never be interpolated directly into shell source.
                if re.search(r'\$\{\{\s*(?:inputs\.|github\.event\.inputs\.|steps\.)', script):
                    raise ValueError(f'{path}: untrusted expression in run step {step.get("name")}')
                result = subprocess.run(['bash', '-n'], input=script, text=True, capture_output=True)
                if result.returncode:
                    raise ValueError(f'{path}: {step.get("name")}: {result.stderr}')
        print(f'OK {path}')


if __name__ == '__main__':
    try: main()
    except (ValueError, yaml.YAMLError) as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
