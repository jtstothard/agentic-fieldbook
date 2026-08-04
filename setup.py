"""Setup script for Agentic Fieldbook v0.1 Hermes plugin."""

from setuptools import find_packages, setup
from pathlib import Path

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8")

with open("VERSION", encoding="utf-8") as f:
    version = f.read().strip()

setup(
    name="agentic-fieldbook",
    version=version,
    author="Jay Stothard",
    author_email="jtstothard@gmail.com",
    description="An operating methodology for autonomous agents — Hermes plugin bundle",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/jtstothard/agentic-fieldbook",
    packages=find_packages(),
    package_data={"agentic_fieldbook.plugins.hitl_gate": ["plugin.yaml"]},
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
    install_requires=[
        "pydantic>=2.0",
        "PyYAML>=6.0",
    ],
    # Hermes will load plugin.py during plugin initialization
    entry_points={
        "hermes_agent.plugins": [
            "agentic-fieldbook = agentic_fieldbook.plugin",
            "hitl-gate = agentic_fieldbook.plugins.hitl_gate",
        ],
    },
)