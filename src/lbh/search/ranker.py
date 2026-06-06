from __future__ import annotations

import math
from pathlib import Path

from lbh.core.fs import classify_layer
from lbh.core.models import RankedFile
from lbh.core.paths import index_dir
from lbh.indexer.store import IndexStore
from lbh.search.query import expand_query


def _contains_score(haystack: str, terms: list[str]) -> tuple[float, list[str]]:
    h = haystack.lower()
    score = 0.0
    hits: list[str] = []
    for t in terms:
        if t and t in h:
            hits.append(t)
            score += 1.0 + min(2.0, len(t) / 12.0)
    return score, hits


class SearchRanker:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.store = IndexStore(index_dir(repo_root) / "files.sqlite")

    def rank(self, query: str, limit: int = 12) -> list[RankedFile]:
        terms = expand_query(query)
        if not terms:
            terms = [query.lower()]
        with self.store.connect() as conn:
            rows = conn.execute("SELECT id, path, content_preview FROM files ORDER BY path").fetchall()
            raw_scores: dict[int, float] = {}
            reasons: dict[int, list[str]] = {}
            paths: dict[int, str] = {}
            for row in rows:
                fid = int(row["id"])
                path = row["path"]
                paths[fid] = path
                score = 0.0
                rs: list[str] = []

                s, hits = _contains_score(path, terms)
                if hits:
                    score += s * 2.5
                    rs.append("path:" + ",".join(hits[:5]))

                sym_rows = conn.execute("SELECT name, signature FROM symbols WHERE file_id = ?", (fid,)).fetchall()
                sym_text = " ".join((r["name"] or "") + " " + (r["signature"] or "") for r in sym_rows)
                s, hits = _contains_score(sym_text, terms)
                if hits:
                    score += s * 2.0
                    rs.append("symbol:" + ",".join(hits[:5]))

                imp_rows = conn.execute("SELECT raw, resolved_path FROM imports WHERE src_file_id = ?", (fid,)).fetchall()
                imp_text = " ".join((r["raw"] or "") + " " + (r["resolved_path"] or "") for r in imp_rows)
                s, hits = _contains_score(imp_text, terms)
                if hits:
                    score += s * 1.5
                    rs.append("import:" + ",".join(hits[:5]))

                s, hits = _contains_score(row["content_preview"] or "", terms)
                if hits:
                    score += s * 1.0
                    rs.append("content:" + ",".join(hits[:5]))

                layer = classify_layer(path)
                if layer != "other":
                    score += 0.25

                if score > 0:
                    raw_scores[fid] = score
                    reasons[fid] = rs

            # Graph expansion: direct import neighbors get a smaller bonus.
            for fid, base_score in list(raw_scores.items()):
                edges = conn.execute(
                    "SELECT src_file_id, dst_file_id FROM edges WHERE src_file_id = ? OR dst_file_id = ?",
                    (fid, fid),
                ).fetchall()
                for edge in edges:
                    other = int(edge["dst_file_id"] if int(edge["src_file_id"]) == fid else edge["src_file_id"])
                    bonus = base_score * 0.18
                    if other not in raw_scores or raw_scores[other] < bonus:
                        raw_scores[other] = raw_scores.get(other, 0.0) + bonus
                    reasons.setdefault(other, []).append(f"graph-neighbor:{paths.get(fid, fid)}")

            ranked = [
                RankedFile(path=paths[fid], score=score, reasons=reasons.get(fid, []), layer=classify_layer(paths[fid]))
                for fid, score in raw_scores.items()
            ]
            ranked.sort(key=lambda r: r.score, reverse=True)

            # Diversity pass: keep strong files but avoid only one layer if alternatives exist.
            selected: list[RankedFile] = []
            layer_counts: dict[str, int] = {}
            for item in ranked:
                count = layer_counts.get(item.layer, 0)
                if len(selected) < max(4, limit // 2) or count < 3 or item.score >= ranked[0].score * 0.7:
                    selected.append(item)
                    layer_counts[item.layer] = count + 1
                if len(selected) >= limit:
                    break
            return selected[:limit]
