import base64
import copy
import unittest
from pathlib import Path

import github_governance as g

FRAGMENT = """---
schema_version: 1
type: article
title: Test
source_url: https://example.com/
added: 2026-10-25
summary: Test
tags: [test]
use_cases: [test]
---
## What it is
Research fragment.
## Why it is interesting
Useful.
## Practical applications
Research.
"""


class FakeGitHub:
    repo = "stefanrossmeier/interesting-items"

    def __init__(self):
        self.pr = {
            "number": 7,
            "state": "open",
            "draft": False,
            "user": {"login": "stefanrossmeier"},
            "body": "AI disclosure: Conrad",
            "head": {
                "sha": "head",
                "ref": "conrad/interesting-item-test",
                "repo": {"full_name": self.repo},
            },
            "base": {"sha": "base", "ref": "main"},
            "labels": [],
            "changed_files": 1,
        }
        self.files = [{"status": "added", "filename": "items/articles/test.md"}]
        self.statuses = []
        self.mode = "100644"
        self.existing = False
        self.checks = []
        self.merged = False
        self.deleted = False
        self.moved_head = False
        self.base_current = True
        self.content = FRAGMENT

    def pages(self, path):
        return self.files

    def status(self, sha, context, passed, description):
        self.statuses = [x for x in self.statuses if x["context"] != context]
        self.statuses.append({"context": context, "state": "success" if passed else "failure"})

    def api(self, path, method="GET", data=None):
        if path == "/pulls/7":
            result = copy.deepcopy(self.pr)
            if self.moved_head and self.statuses:
                result["head"]["sha"] = "changed"
            return result
        if path == "/issues/7/labels":
            self.pr["labels"] = [{"name": x} for x in data["labels"]]
            return {}
        if path.startswith("/git/trees/"):
            sha = path.rsplit("/", 1)[1]
            trees = {
                "base": []
                if not self.existing
                else [{"path": "items", "type": "tree", "sha": "items"}],
                "head": [{"path": "items", "type": "tree", "sha": "items"}],
                "items": [{"path": "articles", "type": "tree", "sha": "articles"}],
                "articles": [{"path": "test.md", "type": "blob", "sha": "blob", "mode": self.mode}],
            }
            return {"tree": trees[sha]}
        if path == "/git/blobs/blob":
            return {
                "content": base64.b64encode(self.content.encode()).decode(),
                "size": len(self.content),
                "encoding": "base64",
            }
        if path == "/git/ref/heads/main":
            return {"object": {"sha": "base" if self.base_current else "newbase"}}
        if path == "/compare/base...head":
            return {"merge_base_commit": {"sha": "base"}}
        if path.startswith("/commits/head/status"):
            return {"statuses": self.statuses, "total_count": len(self.statuses)}
        if path.startswith("/commits/head/check-runs"):
            return {"check_runs": self.checks, "total_count": len(self.checks)}
        if path == "/pulls/7/merge":
            assert data == {"sha": "head", "merge_method": "squash"}
            self.merged = True
            return {"merged": True}
        if path.startswith("/git/refs/heads/") and method == "DELETE":
            self.deleted = True
            return None
        raise AssertionError(path)


class GovernanceTests(unittest.TestCase):
    def test_embedded_workflow_matches_tested_source(self):
        workflow = Path(__file__).parent.parent / "workflows/conrad-governance.yml"
        if not workflow.exists():
            return  # Local generator is independently compiled before publishing.
        embedded = workflow.read_text().split("        run: |\n", 1)[1]
        source = "\n".join(line[10:] for line in embedded.splitlines()) + "\n"
        self.assertEqual(source, (Path(__file__).parent / "github_governance.py").read_text())

    def test_valid_fragment_merges_and_deletes_branch(self):
        gh = FakeGitHub()
        g.process(gh, 7, True)
        self.assertTrue(gh.merged and gh.deleted)
        self.assertEqual(gh.pr["labels"], [{"name": "ai-generated"}])

    def test_disallowed_changes(self):
        for status, filename in [
            ("modified", "items/articles/test.md"),
            ("removed", "items/articles/test.md"),
            ("renamed", "items/articles/test.md"),
            ("added", ".github/workflows/test.md"),
            ("added", "items/articles/test.py"),
            ("added", "items/articles/nested/test.md"),
        ]:
            with self.subTest(status=status, filename=filename):
                gh = FakeGitHub()
                gh.files = [{"status": status, "filename": filename}]
                g.process(gh, 7, True)
                self.assertFalse(gh.merged)
                self.assertEqual(gh.statuses[-1]["state"], "failure")

    def test_regular_new_research_content_only(self):
        for attr, value in [
            ("mode", "120000"),
            ("mode", "100755"),
            ("existing", True),
            ("content", "arbitrary markdown"),
        ]:
            with self.subTest(attr=attr, value=value):
                gh = FakeGitHub()
                setattr(gh, attr, value)
                g.process(gh, 7, True)
                self.assertFalse(gh.merged)

    def test_ci_pending_and_failed_do_not_merge(self):
        for state, conclusion in [("in_progress", None), ("completed", "failure")]:
            gh = FakeGitHub()
            gh.checks = [{"name": "CI", "status": state, "conclusion": conclusion}]
            g.process(gh, 7, True)
            self.assertFalse(gh.merged)

    def test_changed_head_and_base_do_not_merge(self):
        for attr, value in [("moved_head", True), ("base_current", False)]:
            gh = FakeGitHub()
            setattr(gh, attr, value)
            g.process(gh, 7, True)
            self.assertFalse(gh.merged)

    def test_disabled_never_merges(self):
        gh = FakeGitHub()
        g.process(gh, 7, False)
        self.assertFalse(gh.merged)

    def test_setup_never_merges(self):
        gh = FakeGitHub()
        gh.pr["head"]["ref"] = "conrad/github-governance"
        g.process(gh, 7, True)
        self.assertFalse(gh.merged)

    def test_other_repo_only_labels(self):
        gh = FakeGitHub()
        gh.repo = "stefanrossmeier/ordinary"
        g.process(gh, 7, True)
        self.assertFalse(gh.merged)
        self.assertEqual(gh.pr["labels"], [{"name": "ai-generated"}])

    def test_forks_and_other_authors_do_not_merge(self):
        for field in ("author", "fork"):
            gh = FakeGitHub()
            if field == "author":
                gh.pr["user"]["login"] = "someone"
            else:
                gh.pr["head"]["repo"]["full_name"] = "someone/fork"
            g.process(gh, 7, True)
            self.assertFalse(gh.merged)

    def test_human_pr_untouched(self):
        gh = FakeGitHub()
        gh.pr["head"]["ref"] = "human-work"
        gh.pr["body"] = "Ordinary PR"
        g.process(gh, 7, True)
        self.assertEqual(gh.pr["labels"], [])


if __name__ == "__main__":
    unittest.main()
