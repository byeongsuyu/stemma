"""Stemma: a local writing desk, genealogy model and bilingual blog publisher.

The three subpackages depend in one direction only. ``core`` holds the model,
persistence and publication rules and imports neither sibling. ``blog`` renders
and deploys the public site on top of ``core``. ``editor`` serves the writing
desk and mounts the blog's publication screens. ``tests/test_package_layout.py``
enforces that direction.
"""

__version__ = "0.4.1"
