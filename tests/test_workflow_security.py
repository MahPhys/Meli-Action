from pathlib import Path
import re
import unittest
import yaml


class WorkflowSecurityTests(unittest.TestCase):
    def test_checkouts_do_not_persist_credentials_and_actions_are_pinned(self):
        for path in Path('.github/workflows').glob('*.yml'):
            workflow = yaml.safe_load(path.read_text())
            for job in workflow['jobs'].values():
                for step in job.get('steps', []):
                    action = step.get('uses', '')
                    if not action:
                        continue
                    with self.subTest(file=path.name, action=action):
                        if not action.startswith('./'):
                            self.assertRegex(action, r'@[0-9a-f]{40}$')
                        if action.startswith('actions/checkout@'):
                            self.assertIs(step.get('with', {}).get('persist-credentials'), False)

    def test_push_is_branch_scoped_and_token_only_passed_to_push_step(self):
        for path in Path('.github/workflows').glob('*.yml'):
            workflow = yaml.safe_load(path.read_text())
            for job in workflow['jobs'].values():
                for step in job.get('steps', []):
                    script = step.get('run', '')
                    with self.subTest(file=path.name, step=step.get('name')):
                        self.assertNotRegex(script, r'(?m)^\s*git push\b')
                        if 'push_current_branch.sh' in script:
                            self.assertEqual(step.get('env', {}).get('GITHUB_TOKEN'), '${{ github.token }}')
