"""Verify installed-style entry points and the subpackage dependency direction."""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import stemma_graph

import stemma_studio
from stemma_studio.core.application import Studio
from stemma_studio.core.domain import empty_state

SOURCE = Path(stemma_studio.__file__).resolve().parent
# The editor mounts the blog's publication screens, so it may import both siblings.
FORBIDDEN = {"core": ("stemma_studio.blog", "stemma_studio.editor"), "blog": ("stemma_studio.editor",)}


def imported_modules(path, module):
    """Yield every absolute module name imported by one file, resolving relative imports."""
    package = module.rsplit(".", 1)[0]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if not node.level:
                yield node.module
                continue
            base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
            yield base + "." + node.module if node.module else base


class PackageLayoutTests(unittest.TestCase):
    def cli(self, cwd, *arguments):
        environment = dict(os.environ)
        # Subprocesses receive only package roots, never a path to personal data.
        environment["PYTHONPATH"] = os.pathsep.join(
            str(Path(p.__file__).resolve().parents[1]) for p in (stemma_studio, stemma_graph)
        )
        return subprocess.run(
            [sys.executable, "-B", "-m", "stemma_studio.cli", *arguments],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
        )

    def test_cli_default_root_is_working_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            Studio(folder).save(empty_state())
            result = self.cli(folder, "--no-sync", "validate")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["documents"], 0)

    def test_cli_explicit_root_works_outside_data_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "separate-data"
            Studio(root).save(empty_state())
            result = self.cli(folder, "--root", str(root), "--no-sync", "validate")
            self.assertEqual(result.returncode, 0, result.stderr)
            missing = self.cli(folder, "--no-sync", "validate")
            self.assertNotEqual(missing.returncode, 0)

    def test_the_development_runner_puts_global_options_where_the_tool_reads_them(self):
        """`dev.py workspace --root somewhere` has to start, not exit 2.

        The runner supplies the subcommand for the server tasks, and the tool reads
        --root and --no-sync before a subcommand, so anything typed after the task name
        had been landing on the wrong side of it.
        """
        import importlib.util

        from stemma_studio.cli import add_commands
        from stemma_studio.core.__main__ import build_parser

        source = Path(stemma_studio.__file__).resolve().parents[2] / "scripts" / "dev.py"
        spec = importlib.util.spec_from_file_location("dev_runner", source)
        dev = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dev)

        parser, sub = build_parser()
        add_commands(sub)
        for task, typed in (
            ("workspace", ["--root", "/tmp/x"]),
            ("editor", ["--root=/tmp/x", "--port", "9000"]),
            ("blog-admin", ["--root", "/tmp/x", "--read-only"]),
            ("blog", ["--base", "/blog/"]),
            ("studio", ["validate", "--no-sync", "--root", "/tmp/x"]),
        ):
            with self.subTest(task=task):
                module, argv = dev.invocation(task, typed, ".")
                self.assertEqual(module, "stemma_studio.cli")
                # The real parser is the judge of whether the order came out right.
                try:
                    parser.parse_args(argv)
                except SystemExit as stop:
                    self.fail(f"dev.py {task} {' '.join(typed)} -> {argv}, which the tool rejects ({stop.code})")

    def test_documented_command_forms_actually_run(self):
        """Every `stemma ...` line in the docs, checked against the real parser.

        Global options belong before the subcommand, and a doc example that put them
        after it exited 2 for anyone who copied it. Parsing the docs rather than
        restating them is what keeps the two from drifting apart again.
        """
        # The Korean landing page is short prose, but its command blocks stay
        # English, so the parser is the judge of those too.
        docs = [Path("README.md"), Path("README.ko.md"), *sorted(Path("docs").glob("*.md"))]
        found = []
        for doc in docs:
            if not doc.exists():
                continue
            for line in doc.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped.startswith("stemma ") or "<" in stripped or "|" in stripped:
                    continue
                # Documented lines carry trailing "# what this does" comments.
                found.append((doc.name, stripped.split("#")[0].split()))
        self.assertTrue(found, "no documented stemma commands found to check")
        # The real parser, in process: `--help` would short-circuit before argparse
        # rejects a misplaced global option, which is the mistake being guarded against.
        from stemma_studio.cli import add_commands
        from stemma_studio.core.__main__ import build_parser

        for name, argv in found:
            parser, sub = build_parser()
            add_commands(sub)
            try:
                parser.parse_args(argv[1:])
            except SystemExit as stop:
                self.fail(f"{name} documents `{' '.join(argv)}`, which the parser rejects ({stop.code})")

    def test_init_creates_a_usable_root_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            created = self.cli(folder, "init")
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertEqual(json.loads(created.stdout)["created"], "data/studio.json")
            self.assertEqual(self.cli(folder, "--no-sync", "validate").returncode, 0)
            # A second init must never overwrite an existing author's metadata.
            self.assertNotEqual(self.cli(folder, "init").returncode, 0)

    def test_subpackage_dependency_direction(self):
        """The core imports no sibling, and the blog never imports the editor."""
        checked = 0
        for name, forbidden in FORBIDDEN.items():
            for path in sorted((SOURCE / name).rglob("*.py")):
                if "vendor" in path.parts:
                    continue
                module = "stemma_studio." + ".".join(path.relative_to(SOURCE).with_suffix("").parts)
                for imported in imported_modules(path, module):
                    self.assertFalse(imported.startswith(forbidden), f"{module} imports {imported}")
                checked += 1
        self.assertGreater(checked, 10)

    def test_every_screen_the_admin_switches_between_exists_in_its_page(self):
        """A screen named only in the script is a blank page nobody can reach.

        The script hides and shows sections by id and marks the matching top-bar
        link; if either side is renamed alone, the screen silently disappears.
        """
        page = (SOURCE / "blog/admin_frontend/index.html").read_text(encoding="utf-8")
        script = (SOURCE / "blog/admin_frontend/admin.js").read_text(encoding="utf-8")
        listed = re.search(r"for\(const name of \[([^\]]*)\]\)\$\(name\+'-view'\)", script)
        views = re.findall(r"'([a-z]+)'", listed.group(1))
        self.assertIn("settings", views)
        for view in views:
            self.assertIn(f'<section id="{view}-view"', page, view)
        routed = re.search(r"event\.target\.closest\('([^']*)'\)", script).group(1)
        for nav in re.findall(r"#(nav-[a-z]+)", routed):
            self.assertIn(f'<a id="{nav}"', page, f"{nav} is routed but is not a link on the page")
        # Each top-bar link the editor opens must be a screen the admin can route to.
        editor = (SOURCE / "editor/frontend/app.js").read_text(encoding="utf-8")
        for suffix in re.findall(r"'\?view=([a-z]+)'", editor):
            self.assertIn(suffix, views, suffix)

    def test_packaged_frontend_files_sit_inside_the_package(self):
        """An installed wheel must carry every asset the servers read at runtime."""
        for relative in (
            "blog/frontend/site.css",
            "blog/frontend/fonts/MaruBuri-Regular.woff2",
            "blog/admin_frontend/index.html",
            "blog/sample/public-v3.json",
            "blog/math-render.cjs",
            "blog/vendor/katex/katex.cjs",
            "editor/frontend/index.html",
            "editor/frontend/style.css",
            "editor/frontend/i18n.js",
            "blog/admin_frontend/i18n.js",
            "locale/ko.json",
            "locale/en.json",
        ):
            self.assertTrue((SOURCE / relative).is_file(), relative)
