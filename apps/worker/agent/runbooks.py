"""Runbook RAG index and retrieval engine for incident investigation."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import yaml

from apps.api.app.models.enums import EvidenceSourceType
from packages.connectors.models import ConnectorResult

logger = structlog.get_logger()


@dataclass
class RunbookDocument:
    """Parsed runbook with metadata and structured sections."""

    file_name: str
    service: str
    incident_type: str
    owner_team: str
    title: str
    symptoms: list[str] = field(default_factory=list)
    likely_causes: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    raw_markdown: str = ""
    sections: dict[str, str] = field(default_factory=dict)


def parse_runbook_file(path: Path) -> RunbookDocument:
    """Parse a markdown runbook with YAML frontmatter into structured data."""
    content = path.read_text(encoding="utf-8")
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)

    metadata: dict[str, Any] = {}
    body = content
    if frontmatter_match:
        frontmatter_str, body = frontmatter_match.groups()
        try:
            metadata = yaml.safe_load(frontmatter_str) or {}
        except Exception:
            metadata = {}

    service = metadata.get("service", "")
    incident_type = metadata.get("incident_type", "")
    owner_team = metadata.get("owner_team", "")

    # Extract title
    title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem.replace("-", " ").title()

    # Split into sections by markdown headings ##
    sections: dict[str, str] = {}
    current_section = "intro"
    lines = body.splitlines()
    section_lines: list[str] = []

    for line in lines:
        heading_match = re.match(r"^##\s+(.+)$", line)
        if heading_match:
            if section_lines:
                sections[current_section] = "\n".join(section_lines).strip()
                section_lines = []
            current_section = heading_match.group(1).strip().lower()
        else:
            section_lines.append(line)
    if section_lines:
        sections[current_section] = "\n".join(section_lines).strip()

    def extract_bullets(text: str) -> list[str]:
        items: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            # numbered or dash bullet
            bullet_match = re.match(r"^(?:-|\d+\.)\s+(.+)$", line)
            if bullet_match:
                items.append(bullet_match.group(1).strip())
        return items

    symptoms = extract_bullets(sections.get("symptoms", ""))
    likely_causes = extract_bullets(sections.get("likely causes", ""))
    recommended_actions = extract_bullets(sections.get("recommended actions", ""))

    return RunbookDocument(
        file_name=path.name,
        service=service,
        incident_type=incident_type,
        owner_team=owner_team,
        title=title,
        symptoms=symptoms,
        likely_causes=likely_causes,
        recommended_actions=recommended_actions,
        raw_markdown=content,
        sections=sections,
    )


DEFAULT_RUNBOOKS_DIR = Path(__file__).resolve().parents[3] / "runbooks"


class RunbookRetriever:
    """In-memory indexing and hybrid lexical/semantic retrieval for runbooks."""

    def __init__(self, runbooks_dir: Path | str | None = None) -> None:
        if runbooks_dir is None:
            self.runbooks_dir = (
                DEFAULT_RUNBOOKS_DIR if DEFAULT_RUNBOOKS_DIR.exists() else Path("runbooks")
            )
        else:
            self.runbooks_dir = Path(runbooks_dir)
        self.documents: list[RunbookDocument] = []
        self.reload()

    def reload(self) -> None:
        """Scan directory and load all markdown runbooks."""
        self.documents.clear()
        if not self.runbooks_dir.exists():
            return
        for file_path in self.runbooks_dir.glob("*.md"):
            try:
                doc = parse_runbook_file(file_path)
                self.documents.append(doc)
            except Exception as exc:
                logger.warning("runbook_parse_failed", path=str(file_path), error=str(exc))
                continue

    def retrieve(
        self,
        service_name: str | None = None,
        query: str = "",
        top_k: int = 2,
    ) -> list[tuple[RunbookDocument, float]]:
        """Retrieve the most relevant runbooks matching service and incident query."""
        if not self.documents:
            self.reload()

        query_terms = set(re.findall(r"\w+", query.lower()))
        results: list[tuple[RunbookDocument, float]] = []

        for doc in self.documents:
            score = 0.0

            # Service exact match gives significant weight
            if service_name and doc.service:
                if doc.service.lower() == service_name.lower():
                    score += 2.0
                elif service_name.lower() in doc.service.lower():
                    score += 1.0

            # Check query tokens in incident_type and title
            type_terms = set(re.findall(r"\w+", doc.incident_type.lower()))
            title_terms = set(re.findall(r"\w+", doc.title.lower()))

            score += len(query_terms & type_terms) * 1.5
            score += len(query_terms & title_terms) * 1.0

            # Check query tokens in symptoms
            for symptom in doc.symptoms:
                sym_terms = set(re.findall(r"\w+", symptom.lower()))
                overlap = len(query_terms & sym_terms)
                score += overlap * 0.8

            # Check query tokens in full body
            doc_terms = set(re.findall(r"\w+", doc.raw_markdown.lower()))
            body_overlap = len(query_terms & doc_terms)
            score += body_overlap * 0.2

            if score > 0:
                results.append((doc, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def retrieve_as_connector_result(
        self,
        service_name: str | None,
        query: str,
        collected_at: datetime | None = None,
    ) -> list[ConnectorResult]:
        """Retrieve runbooks and convert to ConnectorResults for evidence storage."""
        matches = self.retrieve(service_name=service_name, query=query, top_k=2)
        results: list[ConnectorResult] = []
        now = collected_at or datetime.now(UTC)

        for doc, score in matches:
            action_desc = (
                "; ".join(doc.recommended_actions[:2]) if doc.recommended_actions else "Check logs"
            )
            summary = f"Runbook '{doc.title}' ({doc.file_name}): Recommended action: {action_desc}"
            results.append(
                ConnectorResult(
                    source_type=EvidenceSourceType.RUNBOOK,
                    source_name=f"runbooks/{doc.file_name}",
                    query=f"service={service_name or '*'} query={query}",
                    query_params={
                        "service_name": service_name or "",
                        "query": query,
                        "score": round(score, 2),
                    },
                    summary=summary,
                    raw_data={
                        "file_name": doc.file_name,
                        "title": doc.title,
                        "service": doc.service,
                        "incident_type": doc.incident_type,
                        "owner_team": doc.owner_team,
                        "symptoms": doc.symptoms,
                        "likely_causes": doc.likely_causes,
                        "recommended_actions": doc.recommended_actions,
                        "score": score,
                    },
                    collected_at=now,
                )
            )
        return results
