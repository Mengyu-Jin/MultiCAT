# MultiCat — Multi-Agent LLM Pipeline for Heterogeneous Catalysis Data Extraction

<p align="center">
  <img src="docs/images/toc_graphic.png" alt="Graphical abstract" width="600">
</p>

A large-scale, multi-agent LLM system for extracting structured data from heterogeneous catalysis literature. Automatically extracts reaction conditions and performance data from publisher full-text XML, producing a structured dataset ready for machine learning.

## Overview

```
Scopus DOI search -> XML acquisition -> text packaging -> Screening -> Extraction -> Validation -> Repair -> Judge -> reaction-level table
```

<p align="center">
  <img src="docs/images/figure1_workflow.png" alt="Overall workflow spanning three tracks: data construction, data quality evaluation, and ML-ready analysis" width="900">
</p>

Four LLM agents work in sequence:

| Agent | Model | Role |
|-------|------|------|
| Screening | Gemini 2.5 Flash | Filters out out-of-scope papers (reviews, homogeneous catalysis, fermentation, etc.) |
| Extraction | Gemini 2.5 Flash | Extracts structured reaction records (JSON) from full text |
| Repair | GPT-4.1-mini | Fixes schema-validation errors (up to 2 rounds) |
| Judge | Claude Sonnet | Final semantic-quality adjudication (up to 2 rounds) |

**Dataset scale**: 4,520 papers searched -> 988 relevant -> 647 passed -> **622 papers / 6,973 reaction records**

## Directory Structure

```
MultiCat/
├── src/multicat/                # Core Python package
│   ├── agents/                  # The four agent implementations
│   ├── pipeline/                # Pipeline orchestration CLI
│   ├── text_acquisition/        # XML download, text packaging
│   ├── validator/                # Schema validation
│   ├── database_builder/        # Reaction-table construction + cost reporting
│   └── llm/                      # OpenRouter client + model configuration
├── tests/                        # Unit tests (pytest)
├── prompts/                      # LLM prompt templates
├── schemas/                      # JSON Schema + field-design documentation
├── config.yaml                   # Scopus search configuration
├── .env.example                  # API key template
└── pyproject.toml                # Package definition
```

## Requirements

- Python 3.11+
- Configure the following API keys in `.env` (see `.env.example`):
  - `OPENROUTER_API_KEY` — unified routing to Gemini Flash / GPT-4.1-mini / Claude Sonnet
  - `ELSEVIER_API_KEY` — Elsevier full-text XML access
  - `SCOPUS_API_KEY` — Scopus DOI search

## Installation

```bash
git clone https://github.com/Mengyu-Jin/MultiCat.git
cd MultiCat
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your API keys.

## Running the Pipeline

**Run on specific papers:**
```bash
python -m multicat.pipeline.run_pipeline_cli \
    --paper-ids P000001 P000002 \
    --workers 4 \
    --max-repair-loops 2 \
    --extraction-mode ml_core \
    --skip-existing-pass
```

**Rebuild the reaction-level table:**
```bash
python -m multicat.database_builder.build_reaction_table_v1_cli
```

## Key Design Decisions

- **XML-first**: parses publisher full-text XML (rather than PDF), preserving table structure for reliable extraction.
- **ml_core extraction mode**: uses a blocklist to skip recycling experiments, kinetics tables, and mechanism tables, prioritizing data quality over coverage.
- **Blocklist filtering (not an allowlist)**: newly encountered table types are included by default; only known-noisy types are excluded.
- **Judge has final authority**: a paper the Validator flags as failed but the Judge passes is treated as accepted; the Repair loop follows the Judge's verdict.

## Tests

```bash
pytest tests/
```

## Citation

> Citation details to be added upon publication.
