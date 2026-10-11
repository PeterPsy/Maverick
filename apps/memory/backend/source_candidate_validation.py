"""Validate source search channels before using them in agent evidence."""

from retrieval import source_chunk_matches_by_node


def validated_source_candidates(db, data_root, query, candidates, *, limit):
    matches = source_chunk_matches_by_node(db, data_root, query,
                                          node_ids=[item['id'] for item in candidates], limit=limit)
    validated = []
    for candidate in candidates:
        channels = [channel for channel in candidate['match_sources']
                    if channel != 'source_chunk' or matches.get(candidate['id'])]
        if channels:
            validated.append({**candidate, 'match_sources': channels})
    return validated, matches
