# Vaccin finder for DoctoLib

## Install

Install poetry on your system, then install with

```bash
poetry install
```

## Usage

Create a JSON file containing a lit of centre de santes with the city and name. Set up a webhook on slack and save the hook in the environment variable `SLACK_HOOK`. Then, schedule the `main.py` at a regular interval which can be called as:

```bash
poetry run python main.py --slug-file slugs.json
```