"""Idempotently bootstrap and verify the local DataHub access-control ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publish_semantic_catalog import _headers, validate_local_server  # noqa: E402


ROOT = Path(__file__).resolve().parents[3]
PROFILE_CONTRACT = ROOT / "config/server-access-profiles.v1.json"
SERVING_CONTRACT = ROOT / "src/data/serving_analytics_contract.i4.v1.json"
TAG_URN = "urn:li:tag:AI_SEARCH_ALLOWED"
DOMAIN_NAMES = {
    "rooms": "PMS Rooms",
    "membership": "CRM Membership",
    "food_and_beverage": "POS Food and Beverage",
    "facility": "Facility",
    "banquet": "Banquet",
}


def _proposal(urn: str, entity_type: str, aspect_name: str, aspect: dict[str, Any]) -> dict[str, Any]:
    return {"proposal": {"entityType": entity_type, "entityUrn": urn, "changeType": "UPSERT",
                         "aspectName": aspect_name, "aspect": {"contentType": "application/json",
                         "value": json.dumps(aspect, sort_keys=True, separators=(",", ":"))}}}


def _request_json(request: Request, timeout: float, opener: Callable[..., Any]) -> Any:
    with opener(request, timeout=timeout) as response:
        body = response.read()
    return json.loads(body) if body else None


def _ingest(server: str, token: str, proposal: dict[str, Any], timeout: float,
            opener: Callable[..., Any]) -> None:
    _request_json(Request(f"{server.rstrip('/')}/aspects?action=ingestProposal",
                          data=json.dumps(proposal).encode(), headers=_headers(token), method="POST"),
                  timeout, opener)


def _dataset_urn(fqn: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:trino,{fqn},PROD)"


def _fqn(urn: str) -> str:
    return urn.split(",", 2)[1]


def _dataset_urns(server: str, token: str, timeout: float,
                  opener: Callable[..., Any]) -> list[str]:
    query = "query($input: SearchAcrossEntitiesInput!){searchAcrossEntities(input:$input){searchResults{entity{urn}}}}"
    body = json.dumps({"query": query, "variables": {"input": {
        "types": ["DATASET"], "query": "*", "start": 0, "count": 1000}}}).encode()
    result = _request_json(Request(f"{server.rstrip('/')}/api/graphql", data=body,
                                   headers=_headers(token), method="POST"), timeout, opener)
    if result.get("errors"):
        raise RuntimeError("DataHub rejected governed dataset discovery")
    return [item["entity"]["urn"] for item in result["data"]["searchAcrossEntities"]["searchResults"]]


def _source_domain(fqn: str) -> str | None:
    return next((name for prefix, name in (("pms.", "rooms"), ("crm.", "membership"),
                 ("pos.", "food_and_beverage"), ("facility.", "facility"),
                 ("banquet.", "banquet")) if fqn.startswith(prefix)), None)


def serving_domains(views: list[dict[str, Any]]) -> dict[str, list[str]]:
    upstreams = {view["fqn"]: view["upstream_fqns"] for view in views}

    def resolve(fqn: str, seen: set[str]) -> set[str]:
        direct = _source_domain(fqn)
        if direct:
            return {direct}
        if fqn in seen:
            raise ValueError(f"cyclic serving lineage: {fqn}")
        return set().union(*(resolve(item, seen | {fqn}) for item in upstreams.get(fqn, ())))

    return {fqn: sorted(resolve(fqn, set())) for fqn in upstreams}


def _policy_urn(profile_id: str) -> str:
    digest = hashlib.sha256(f"answervice:{profile_id}:view-entity:v1".encode()).hexdigest()[:32]
    return f"urn:li:dataHubPolicy:answervice-{digest}"


def bootstrap(server: str, token: str, timeout: float = 30,
              opener: Callable[..., Any] = urlopen) -> dict[str, Any]:
    validate_local_server(server)
    contract = json.loads(PROFILE_CONTRACT.read_text(encoding="utf-8"))
    profiles = contract["profiles"]
    database_domains = contract["database_domains"]
    views = json.loads(SERVING_CONTRACT.read_text(encoding="utf-8"))["views"]

    for profile_id, profile in profiles.items():
        username = profile["datahub_actor"].rsplit(":", 1)[-1]
        for aspect, value in (("corpUserKey", {"username": username}),
                              ("corpUserInfo", {"active": True, "displayName": username})):
            _ingest(server, token, _proposal(profile["datahub_actor"], "corpuser", aspect, value), timeout, opener)
        policy = {"type": "METADATA", "state": "ACTIVE", "editable": True,
                  "displayName": f"Answervice {profile_id} View Entity",
                  "description": "Server-managed explicit profile View Entity grant",
                  "privileges": ["VIEW_ENTITY"],
                  "actors": {"users": [profile["datahub_actor"]], "groups": [],
                             "allUsers": False, "allGroups": False, "resourceOwners": False},
                  "resources": {"filter": {"criteria": [{"field": "DOMAIN", "condition": "EQUALS",
                                  "values": sorted({database_domains[item] for item in profile["database_grants"]})}]}}}
        policy_urn = _policy_urn(profile_id)
        _ingest(server, token, _proposal(policy_urn, "dataHubPolicy", "dataHubPolicyKey",
                                        {"id": policy_urn.rsplit(":", 1)[-1]}), timeout, opener)
        _ingest(server, token, _proposal(policy_urn, "dataHubPolicy",
                                        "dataHubPolicyInfo", policy), timeout, opener)

    for domain_id, name in DOMAIN_NAMES.items():
        urn = f"urn:li:domain:{domain_id}"
        _ingest(server, token, _proposal(urn, "domain", "domainKey", {"id": domain_id}), timeout, opener)
        _ingest(server, token, _proposal(urn, "domain", "domainProperties",
                                        {"name": name, "description": "Answervice governed asset domain"}),
                timeout, opener)
    _ingest(server, token, _proposal(TAG_URN, "tag", "tagKey", {"name": "AI_SEARCH_ALLOWED"}), timeout, opener)
    _ingest(server, token, _proposal(TAG_URN, "tag", "tagProperties",
                                    {"name": "AI_SEARCH_ALLOWED", "description": "Approved for AI search context"}),
            timeout, opener)

    source_assets = []
    for urn in _dataset_urns(server, token, timeout, opener):
        domain = _source_domain(_fqn(urn))
        if not domain:
            continue
        source_assets.append(urn)
        _ingest(server, token, _proposal(urn, "dataset", "domains",
                                        {"domains": [f"urn:li:domain:{domain}"]}), timeout, opener)
        _ingest(server, token, _proposal(urn, "dataset", "globalTags",
                                        {"tags": [{"tag": TAG_URN}]}), timeout, opener)

    resolved = serving_domains(views)
    edges = []
    for view in views:
        urn = view["urn"]
        domains = [f"urn:li:domain:{item}" for item in resolved[view["fqn"]]]
        _ingest(server, token, _proposal(urn, "dataset", "domains", {"domains": domains}), timeout, opener)
        _ingest(server, token, _proposal(urn, "dataset", "globalTags", {"tags": [{"tag": TAG_URN}]}), timeout, opener)
        edges.extend({"downstreamUrn": urn, "upstreamUrn": _dataset_urn(item)} for item in view["upstream_fqns"])
    query = "mutation($input: UpdateLineageInput!){updateLineage(input:$input)}"
    body = json.dumps({"query": query, "variables": {"input": {"edgesToAdd": edges, "edgesToRemove": []}}}).encode()
    result = _request_json(Request(f"{server.rstrip('/')}/api/graphql", data=body,
                                   headers=_headers(token), method="POST"), timeout, opener)
    if result.get("errors"):
        raise RuntimeError("DataHub rejected serving lineage bootstrap")
    return {"status": "BOOTSTRAPPED", "profiles": len(profiles), "domains": len(DOMAIN_NAMES),
            "source_assets": len(source_assets), "serving_assets": len(views), "lineage_edges": len(edges)}


def _entity(server: str, urn: str, aspects: list[str], token: str, timeout: float,
            opener: Callable[..., Any]) -> dict[str, Any]:
    endpoint = f"{server.rstrip('/')}/entitiesV2/{quote(urn, safe='')}?aspects=List({','.join(aspects)})"
    return _request_json(Request(endpoint, headers=_headers(token), method="GET"), timeout, opener)


def verify(server: str, token: str, timeout: float = 30,
           opener: Callable[..., Any] = urlopen) -> dict[str, Any]:
    validate_local_server(server)
    contract = json.loads(PROFILE_CONTRACT.read_text(encoding="utf-8"))
    profiles = contract["profiles"]
    database_domains = contract["database_domains"]
    views = json.loads(SERVING_CONTRACT.read_text(encoding="utf-8"))["views"]
    expected_domains = serving_domains(views)
    for profile_id, profile in profiles.items():
        policy = _entity(server, _policy_urn(profile_id), ["dataHubPolicyInfo"], token, timeout, opener)
        try:
            value = policy["aspects"]["dataHubPolicyInfo"]["value"]
        except KeyError as exc:
            raise ValueError(f"missing profile policy: {profile_id}") from exc
        criteria = value["resources"]["filter"]["criteria"][0]
        granted_domains = sorted({database_domains[item] for item in profile["database_grants"]})
        if value["actors"]["users"] != [profile["datahub_actor"]] or criteria["values"] != granted_domains:
            raise ValueError(f"profile policy mismatch: {profile_id}")
        profile_token = os.getenv(profile["datahub_token_env"])
        if not profile_token:
            raise ValueError(f"missing profile token: {profile['datahub_token_env']}")
        body = json.dumps({"query": "{me{corpUser{urn}}}"}).encode()
        me = _request_json(Request(f"{server.rstrip('/')}/api/graphql", data=body,
                                   headers=_headers(profile_token), method="POST"), timeout, opener)
        if me.get("data", {}).get("me", {}).get("corpUser", {}).get("urn") != profile["datahub_actor"]:
            raise ValueError(f"profile token actor mismatch: {profile_id}")
    source_count = 0
    for urn in _dataset_urns(server, token, timeout, opener):
        domain = _source_domain(_fqn(urn))
        if not domain:
            continue
        source_count += 1
        aspects = _entity(server, urn, ["domains", "globalTags"], token, timeout, opener)["aspects"]
        if aspects["domains"]["value"]["domains"] != [f"urn:li:domain:{domain}"]:
            raise ValueError(f"source domain mismatch: {_fqn(urn)}")
        if TAG_URN not in {item["tag"] for item in aspects["globalTags"]["value"]["tags"]}:
            raise ValueError(f"source tag mismatch: {_fqn(urn)}")
    for view in views:
        entity = _entity(server, view["urn"], ["domains", "globalTags", "upstreamLineage"], token, timeout, opener)
        aspects = entity["aspects"]
        actual_domains = sorted(item.rsplit(":", 1)[-1] for item in aspects["domains"]["value"]["domains"])
        if actual_domains != expected_domains[view["fqn"]]:
            raise ValueError(f"serving domain mismatch: {view['fqn']}")
        if TAG_URN not in {item["tag"] for item in aspects["globalTags"]["value"]["tags"]}:
            raise ValueError(f"serving tag mismatch: {view['fqn']}")
        actual_upstreams = {item["dataset"] for item in aspects["upstreamLineage"]["value"]["upstreams"]}
        if not {_dataset_urn(item) for item in view["upstream_fqns"]}.issubset(actual_upstreams):
            raise ValueError(f"serving lineage mismatch: {view['fqn']}")
    return {"status": "VERIFIED", "profiles": len(profiles), "source_assets": source_count,
            "serving_assets": len(views)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "verify"))
    parser.add_argument("--server", default=os.getenv("DATAHUB_GMS_URL", "http://localhost:18081"))
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    token = os.getenv("DATAHUB_BOOTSTRAP_TOKEN")
    if not token:
        parser.error("DATAHUB_BOOTSTRAP_TOKEN is required")
    result = bootstrap(args.server, token, args.timeout) if args.command == "bootstrap" else verify(args.server, token, args.timeout)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
