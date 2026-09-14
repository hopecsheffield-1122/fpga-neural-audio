"""Smoke tests verifying the package is installed correctly."""

from fpga_neural_audio import __version__


def test_version_is_a_string() -> None:
    """Package should expose a version string."""
    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_version_has_semver_shape() -> None:
    """Version should have at least two dots (major.minor.patch)."""
    parts = __version__.split(".")
    assert len(parts) >= 2
