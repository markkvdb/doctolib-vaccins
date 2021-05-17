import os
import json
import datetime
import json
from pathlib import Path
from typing import Optional

import requests
import click
from ratelimit import limits, sleep_and_retry
from pydantic import BaseModel, HttpUrl
from loguru import logger
from rich.logging import RichHandler
from slack_webhook import Slack


# Set-up loggers
logger.configure(
    handlers=[
        {
            "sink": RichHandler(),
            "format": "<level>{message}</level>",
        }
    ]
)
slack = Slack(url=os.environ["SLACK_HOOK"])


class CentreSante(BaseModel):
    """Centre de Sante in DoctoLib."""

    ville: str
    name: str

    def url(self) -> HttpUrl:
        """Get the URL of the center."""
        return f"https://www.doctolib.fr/centre-de-sante/{self.ville}/{self.name}"


class Notification:

    file_path: Path = "notifications.json"
    delay_minutes: float = 30

    def __init__(self, id):
        self.id = str(id)
        self.data = json.loads(open(self.file_path).read())

    def should_warn(self):
        if self.id not in self.data:
            return True
        previous = datetime.datetime.fromisoformat(self.data[self.id])
        now = datetime.datetime.utcnow()
        return previous + datetime.timedelta(minutes=self.delay_minutes) < now

    def register_notification(self):
        now = datetime.datetime.utcnow().isoformat()
        self.data[self.id] = now

        with open(self.file_path, "w") as f:
            f.write(json.dumps(self.data))

    def post_notification(self, message):
        if not self.should_warn():
            return

        slack.post(text=message)

        self.register_notification()


@sleep_and_retry
@limits(calls=1, period=0.1)
def call_doctolib(url: str, params: Optional[dict] = None) -> requests.Response:
    """Call doctolib with rate limiter."""
    r = requests.get(f"https://www.doctolib.fr/{url}", params=params)
    r.raise_for_status()

    return r.json()


@click.command()
@click.option(
    "--slug-file",
    type=click.Path(exists=True),
    help="Path to JSON file containing slugs of vaccination centers.",
)
def find_vaccin(slug_file: click.Path):
    with open(slug_file, "r") as f:
        slugs = json.load(f)

    centers = [CentreSante(**center_dict) for center_dict in slugs]

    for center in centers:
        data = call_doctolib(f"/booking/{center.name}.json")["data"]
        id = data["profile"]["id"]

        has_availability = [a for a in data["agendas"] if not a["booking_disabled"]]

        if not has_availability:
            logger.warning(f'No open agendas at "{center.name}"')
            continue

        try:
            visit_motive_id = [
                v["id"]
                for v in data["visit_motives"]
                if v["name"].startswith("1")
                and "pfizer" in v["name"].lower()
                or "moderna" in v["name"].lower()
            ][0]
        except IndexError:
            logger.warning(f'Cannot find a visite motive at "{center.name}"')
            continue

        agendas_id = "-".join([str(a["id"]) for a in data["agendas"]])

        total = call_doctolib(
            url="/availabilities.json",
            params={
                "start_date": datetime.datetime.today().date().isoformat(),
                "visit_motive_ids": visit_motive_id,
                "agenda_ids": agendas_id,
            },
        )["total"]

        logger.info(f'Found {total} availabilities at "{center.name}"')

        if total >= 2:
            Notification(id=id).post_notification(
                f"*{total}* appointments available at center <{center.url()}|{center.name}>"
            )


if __name__ == "__main__":
    find_vaccin()
